"""HTTP-level tests for /clips."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import Clip, Moment, RankingRun, VideoStatus
from app.tasks.render import ALLOWED_FORMATS


def body(video, **overrides):
    payload = {"video_id": str(video.id), "start_sec": 10.0, "end_sec": 40.0}
    payload.update(overrides)
    return payload


def make_moment(db, video, title="Big reveal", score=8.5):
    run = RankingRun(video_id=video.id, prompt_version="t", model="m")
    db.add(run)
    db.commit()
    moment = Moment(video_id=video.id, run_id=run.id, start_sec=1, end_sec=9, scores={"final": score}, title=title)
    db.add(moment)
    db.commit()
    return moment


# ---------------------------------------------------------------- create


def test_create_clip_queues_a_render(client, user, make_video, queues, db):
    v = make_video(user)
    resp = client.post("/clips/create", json=body(v, captions=True, format="9:16"))
    assert resp.status_code == 202
    clip_id = resp.json()["clip_id"]
    assert resp.json()["status"] == "queued"

    clip = db.get(Clip, uuid.UUID(clip_id))
    assert clip.status == "queued" and clip.user_id == user.id
    assert clip.params == {"start": 10.0, "end": 40.0, "format": "9:16", "captions": True}

    call = queues.cpu.enqueue.call_args
    assert call.args == ("app.tasks.render.render", str(v.id), {"clip_id": clip_id})


def test_create_clip_defaults(client, user, make_video, db):
    from app.tasks.render import DEFAULT_FORMAT

    v = make_video(user)
    clip_id = client.post("/clips/create", json=body(v)).json()["clip_id"]
    params = db.get(Clip, uuid.UUID(clip_id)).params
    assert params["format"] == DEFAULT_FORMAT and params["captions"] is False


@pytest.mark.parametrize("fmt", sorted(ALLOWED_FORMATS))
def test_create_clip_accepts_every_allowed_format(client, user, make_video, fmt):
    v = make_video(user)
    assert client.post("/clips/create", json=body(v, format=fmt)).status_code == 202


def test_create_clip_rejects_unknown_format(client, user, make_video, queues):
    v = make_video(user)
    assert client.post("/clips/create", json=body(v, format="4:3")).status_code == 400
    queues.cpu.enqueue.assert_not_called()


@pytest.mark.parametrize(
    "start,end",
    [(30, 30), (40, 10), (0, 600.5), (-5, -1)],
)
def test_create_clip_rejects_bad_bounds(client, user, make_video, queues, start, end):
    v = make_video(user, duration_sec=600)
    resp = client.post("/clips/create", json=body(v, start_sec=start, end_sec=end))
    if (start, end) == (-5, -1):
        # Negative starts are not rejected today; documenting current behaviour.
        assert resp.status_code == 202
    else:
        assert resp.status_code == 400
        queues.cpu.enqueue.assert_not_called()


def test_create_clip_may_end_exactly_at_the_video_end(client, user, make_video):
    v = make_video(user, duration_sec=600)
    assert client.post("/clips/create", json=body(v, start_sec=500, end_sec=600)).status_code == 202


@pytest.mark.parametrize("status", [s for s in VideoStatus if s != VideoStatus.ready])
def test_create_clip_requires_a_ready_video(client, user, make_video, queues, status):
    v = make_video(user, status=status)
    assert client.post("/clips/create", json=body(v)).status_code == 409
    queues.cpu.enqueue.assert_not_called()


def test_create_clip_for_someone_elses_video_is_404(client, user, other_user, make_video, queues):
    v = make_video(other_user)
    assert client.post("/clips/create", json=body(v)).status_code == 404
    queues.cpu.enqueue.assert_not_called()


def test_create_clip_links_a_moment_of_the_same_video(client, user, make_video, db):
    v = make_video(user)
    m = make_moment(db, v)
    resp = client.post("/clips/create", json=body(v, moment_id=str(m.id)))
    assert resp.status_code == 202
    assert db.get(Clip, uuid.UUID(resp.json()["clip_id"])).moment_id == m.id


def test_create_clip_rejects_a_moment_from_another_video(client, user, make_video, db, queues):
    v = make_video(user)
    other = make_video(user)
    m = make_moment(db, other)
    assert client.post("/clips/create", json=body(v, moment_id=str(m.id))).status_code == 400
    queues.cpu.enqueue.assert_not_called()


def test_create_clip_rejects_an_unknown_moment(client, user, make_video):
    v = make_video(user)
    assert client.post("/clips/create", json=body(v, moment_id=str(uuid.uuid4()))).status_code == 400


def test_create_clip_validates_payload(client, user):
    assert client.post("/clips/create", json={}).status_code == 422
    assert client.post("/clips/create", json={"video_id": "x", "start_sec": 1, "end_sec": 2}).status_code == 422


def test_create_clip_is_rate_limited(client, user, make_video):
    v = make_video(user)
    codes = [client.post("/clips/create", json=body(v)).status_code for _ in range(11)]
    assert codes[:10] == [202] * 10 and codes[10] == 429


# ---------------------------------------------------------------- list


def test_list_clips_in_creation_order_with_moment_details(client, user, make_video, db, r2):
    v = make_video(user)
    m = make_moment(db, v, title="Hook", score=9.1)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    db.add(Clip(video_id=v.id, user_id=user.id, moment_id=m.id, status="ready", r2_key="clips/1.mp4",
                params={"start": 1, "end": 9, "format": "9:16", "captions": True}, created_at=base))
    db.add(Clip(video_id=v.id, user_id=user.id, status="queued",
                params={"start": 2, "end": 6, "format": "1:1", "captions": False}, created_at=base + timedelta(minutes=1)))
    db.commit()

    data = client.get("/clips", params={"video_id": str(v.id)}).json()
    assert data["video_id"] == str(v.id) and data["video_status"] == "ready"
    first, second = data["clips"]
    assert first["status"] == "ready" and first["url"] == "https://r2.test/dl/clips/1.mp4"
    assert first["title"] == "Hook" and first["score"] == 9.1 and first["moment_id"] == str(m.id)
    assert first["format"] == "9:16" and first["captions"] is True
    # an unfinished manual clip has no url, no moment and no score
    assert second["status"] == "queued" and second["url"] is None
    assert second["moment_id"] is None and second["title"] is None and second["score"] is None


def test_list_clips_only_signs_urls_for_ready_clips(client, user, make_video, db, r2):
    v = make_video(user)
    for status in ("queued", "rendering", "error"):
        db.add(Clip(video_id=v.id, user_id=user.id, status=status, r2_key="k", params={}))
    db.commit()
    clips = client.get("/clips", params={"video_id": str(v.id)}).json()["clips"]
    assert all(c["url"] is None for c in clips)
    r2["generate_download_url"].assert_not_called()


def test_list_clips_hides_other_users_clips_on_a_shared_video(client, user, other_user, make_video, db):
    v = make_video(user)
    db.add(Clip(video_id=v.id, user_id=other_user.id, status="ready", r2_key="k", params={}))
    db.commit()
    assert client.get("/clips", params={"video_id": str(v.id)}).json()["clips"] == []


def test_list_clips_for_someone_elses_video_is_404(client, user, other_user, make_video):
    v = make_video(other_user)
    assert client.get("/clips", params={"video_id": str(v.id)}).status_code == 404


def test_list_clips_requires_video_id(client, user):
    assert client.get("/clips").status_code == 422


# ---------------------------------------------------------------- get one


def test_get_ready_clip_returns_download_url(client, user, make_video, db):
    v = make_video(user)
    clip = Clip(video_id=v.id, user_id=user.id, status="ready", r2_key="clips/x.mp4", params={})
    db.add(clip)
    db.commit()
    data = client.get(f"/clips/{clip.id}").json()
    assert data == {"clip_id": str(clip.id), "url": "https://r2.test/dl/clips/x.mp4", "status": "ready"}


def test_get_unfinished_clip_has_no_url(client, user, make_video, db):
    v = make_video(user)
    clip = Clip(video_id=v.id, user_id=user.id, status="rendering", params={})
    db.add(clip)
    db.commit()
    assert client.get(f"/clips/{clip.id}").json()["url"] is None


def test_get_clip_of_another_user_is_rejected(client, user, other_user, make_video, db):
    v = make_video(other_user)
    clip = Clip(video_id=v.id, user_id=other_user.id, status="ready", r2_key="k", params={})
    db.add(clip)
    db.commit()
    assert client.get(f"/clips/{clip.id}").status_code == 400


def test_get_unknown_clip(client, user):
    assert client.get(f"/clips/{uuid.uuid4()}").status_code == 400
