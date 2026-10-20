"""HTTP-level tests for /videos. Auth, storage and queues are faked (see conftest)."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from botocore.exceptions import ClientError

from app.api import video as video_api
from app.db.models import Clip, Moment, RankingRun, Video, VideoStatus

MB = 1024 * 1024


def client_error(code):
    return ClientError({"Error": {"Code": code}}, "op")


def uploading(make_video, user, **pipeline):
    return make_video(user, status=VideoStatus.uploading, pipeline=pipeline)


def multipart(make_video, user, part_count=3):
    return uploading(
        make_video,
        user,
        upload={"mode": "multipart", "upload_id": "u1", "part_size": 1, "part_count": part_count},
    )


# ---------------------------------------------------------------- init


def test_init_small_file_uses_single_put(client, user, db, r2):
    resp = client.post("/videos/init", json={"filename": "Talk.MOV", "size": 5 * MB})
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "single"
    assert body["upload_url"] == "https://r2.test/put"

    video = db.get(Video, uuid.UUID(body["video_id"]))
    assert video.status == VideoStatus.uploading
    assert video.user_id == user.id
    assert video.r2_key.endswith("/original.mov")
    assert video.pipeline == {"upload": {"mode": "single"}}
    assert r2["generate_upload_url"].call_args.args[1] == "video/quicktime"


def test_init_unknown_extension_defaults_to_mp4(client, user, r2):
    client.post("/videos/init", json={"filename": "clip.webm", "size": 10})
    assert r2["generate_upload_url"].call_args.args[1] == "video/mp4"


def test_init_large_file_starts_multipart(client, user, db):
    size = 40 * 16 * MB + 1  # 41 parts of 16 MiB
    resp = client.post("/videos/init", json={"filename": "vod.mkv", "size": size})
    body = resp.json()
    assert body["mode"] == "multipart"
    assert body["upload_id"] == "upload-123"
    assert body["part_size"] == video_api.PART_SIZE
    assert body["part_count"] == 41
    video = db.get(Video, uuid.UUID(body["video_id"]))
    assert video.pipeline["upload"]["upload_id"] == "upload-123"


def test_init_threshold_boundary(client, user):
    below = client.post("/videos/init", json={"filename": "a.mp4", "size": video_api.MULTIPART_THRESHOLD - 1})
    at = client.post("/videos/init", json={"filename": "b.mp4", "size": video_api.MULTIPART_THRESHOLD})
    assert below.json()["mode"] == "single"
    assert at.json()["mode"] == "multipart"


def test_init_rejects_oversize(client, user):
    resp = client.post("/videos/init", json={"filename": "a.mp4", "size": video_api.MAX_SIZE + 1})
    assert resp.status_code == 413


@pytest.mark.parametrize("size", [0, -5])
def test_init_rejects_non_positive_size(client, user, size):
    assert client.post("/videos/init", json={"filename": "a.mp4", "size": size}).status_code == 422


def test_init_requires_filename(client, user):
    assert client.post("/videos/init", json={"size": 10}).status_code == 422


def test_init_storage_failure_returns_500_and_stores_nothing(client, user, db, r2):
    r2["generate_upload_url"].side_effect = RuntimeError("r2 down")
    resp = client.post("/videos/init", json={"filename": "a.mp4", "size": 10})
    assert resp.status_code == 500
    assert db.query(Video).count() == 0


def test_init_multipart_start_failure_returns_500(client, user, r2):
    r2["create_multipart_upload"].side_effect = RuntimeError("nope")
    resp = client.post("/videos/init", json={"filename": "a.mp4", "size": 200 * MB})
    assert resp.status_code == 500


def test_init_embedding_failure_does_not_block_upload(client, user, db):
    resp = client.post("/videos/init", json={"filename": "a.mp4", "size": 10})
    assert resp.status_code == 200
    assert db.get(Video, uuid.UUID(resp.json()["video_id"])).title_embedding is None


def test_init_is_rate_limited(client, user):
    codes = [client.post("/videos/init", json={"filename": "a.mp4", "size": 10}).status_code for _ in range(6)]
    assert codes == [200] * 5 + [429]


def test_init_orphaned_multipart_is_aborted_when_db_commit_fails(client, user, r2, monkeypatch):
    from sqlalchemy.orm import Session

    def boom(self):
        raise RuntimeError("db down")

    monkeypatch.setattr(Session, "commit", boom)
    resp = client.post("/videos/init", json={"filename": "a.mp4", "size": 200 * MB})
    assert resp.status_code == 500
    r2["abort_multipart_upload"].assert_called_once()


# ---------------------------------------------------------------- parts


def test_sign_parts_returns_urls(client, user, make_video):
    v = multipart(make_video, user)
    resp = client.post(f"/videos/{v.id}/parts", json={"part_numbers": [1, 3]})
    assert resp.status_code == 200
    assert resp.json()["urls"] == {"1": "https://r2.test/part/1", "3": "https://r2.test/part/3"}


@pytest.mark.parametrize("numbers", [[0], [4], [1, 99]])
def test_sign_parts_rejects_out_of_range(client, user, make_video, numbers):
    v = multipart(make_video, user)
    assert client.post(f"/videos/{v.id}/parts", json={"part_numbers": numbers}).status_code == 400


def test_sign_parts_validates_batch_size(client, user, make_video):
    v = multipart(make_video, user)
    assert client.post(f"/videos/{v.id}/parts", json={"part_numbers": []}).status_code == 422
    too_many = list(range(1, video_api.MAX_PARTS_PER_SIGN_BATCH + 2))
    assert client.post(f"/videos/{v.id}/parts", json={"part_numbers": too_many}).status_code == 422


def test_sign_parts_conflict_when_not_multipart(client, user, make_video):
    v = uploading(make_video, user, upload={"mode": "single"})
    assert client.post(f"/videos/{v.id}/parts", json={"part_numbers": [1]}).status_code == 409


def test_sign_parts_conflict_when_not_uploading(client, user, make_video):
    v = make_video(user, status=VideoStatus.ready)
    assert client.post(f"/videos/{v.id}/parts", json={"part_numbers": [1]}).status_code == 409


def test_sign_parts_storage_failure(client, user, make_video, r2):
    v = multipart(make_video, user)
    r2["generate_part_upload_urls"].side_effect = RuntimeError("x")
    assert client.post(f"/videos/{v.id}/parts", json={"part_numbers": [1]}).status_code == 500


# ---------------------------------------------------------------- upload-status


def test_upload_status_not_uploading(client, user, make_video):
    v = make_video(user, status=VideoStatus.ready)
    assert client.get(f"/videos/{v.id}/upload-status").json() == {"status": "ready", "resumable": False}


def test_upload_status_single_returns_fresh_url(client, user, make_video):
    v = uploading(make_video, user, upload={"mode": "single"})
    body = client.get(f"/videos/{v.id}/upload-status").json()
    assert body["resumable"] is True and body["upload_url"] == "https://r2.test/put"


def test_upload_status_single_url_failure(client, user, make_video, r2):
    v = uploading(make_video, user, upload={"mode": "single"})
    r2["generate_upload_url"].side_effect = RuntimeError("x")
    assert client.get(f"/videos/{v.id}/upload-status").status_code == 500


def test_upload_status_multipart_lists_parts(client, user, make_video, r2):
    v = multipart(make_video, user)
    r2["list_uploaded_parts"].return_value = [{"part_number": 1, "etag": '"a"', "size": 5}]
    body = client.get(f"/videos/{v.id}/upload-status").json()
    assert body["resumable"] is True
    assert body["uploaded_parts"] == [{"part_number": 1, "etag": '"a"', "size": 5}]
    assert body["upload_id"] == "u1" and body["part_count"] == 3


def test_upload_status_expired_upload_marks_video_errored(client, user, make_video, r2, db):
    v = multipart(make_video, user)
    r2["list_uploaded_parts"].side_effect = client_error("NoSuchUpload")
    body = client.get(f"/videos/{v.id}/upload-status").json()
    assert body["resumable"] is False and body["reason"] == "upload_expired"
    db.refresh(v)
    assert v.status == VideoStatus.error
    assert "upload" not in v.pipeline


def test_upload_status_other_storage_error(client, user, make_video, r2):
    v = multipart(make_video, user)
    r2["list_uploaded_parts"].side_effect = client_error("InternalError")
    assert client.get(f"/videos/{v.id}/upload-status").status_code == 500


# ---------------------------------------------------------------- complete


def test_complete_single_success_enqueues_ingest(client, user, make_video, queues, db):
    v = uploading(make_video, user, upload={"mode": "single"})
    resp = client.post("/videos/complete", json={"video_id": str(v.id), "content_type": "video/mp4"})
    assert resp.status_code == 200
    db.refresh(v)
    assert v.status == VideoStatus.uploaded
    assert v.content_type == "video/mp4"
    assert "upload" not in v.pipeline
    assert queues.io.enqueue.call_args.args == ("app.tasks.ingest.ingest", str(v.id))


def test_complete_single_size_mismatch(client, user, make_video, r2, queues):
    v = uploading(make_video, user, upload={"mode": "single"})
    r2["head_object_size"].return_value = 999
    assert client.post("/videos/complete", json={"video_id": str(v.id)}).status_code == 400
    queues.io.enqueue.assert_not_called()


def test_complete_single_missing_object(client, user, make_video, r2):
    v = uploading(make_video, user, upload={"mode": "single"})
    r2["head_object_size"].return_value = None
    assert client.post("/videos/complete", json={"video_id": str(v.id)}).status_code == 400


def test_complete_multipart_success(client, user, make_video, r2, queues, db):
    v = multipart(make_video, user, part_count=2)
    parts = [{"part_number": 2, "etag": '"b"'}, {"part_number": 1, "etag": '"a"'}]
    resp = client.post("/videos/complete", json={"video_id": str(v.id), "parts": parts})
    assert resp.status_code == 200
    r2["complete_multipart_upload"].assert_called_once()
    db.refresh(v)
    assert v.status == VideoStatus.uploaded
    queues.io.enqueue.assert_called_once()


@pytest.mark.parametrize(
    "parts",
    [
        None,
        [],
        [{"part_number": 1, "etag": "a"}],
        [{"part_number": 1, "etag": "a"}, {"part_number": 1, "etag": "a"}],
        [{"part_number": 1, "etag": "a"}, {"part_number": 3, "etag": "c"}],
    ],
)
def test_complete_multipart_rejects_bad_part_lists(client, user, make_video, queues, parts):
    v = multipart(make_video, user, part_count=2)
    resp = client.post("/videos/complete", json={"video_id": str(v.id), "parts": parts})
    assert resp.status_code == 400
    queues.io.enqueue.assert_not_called()


def test_complete_multipart_storage_rejection(client, user, make_video, r2, queues):
    v = multipart(make_video, user, part_count=1)
    r2["complete_multipart_upload"].side_effect = client_error("InvalidPart")
    resp = client.post(
        "/videos/complete", json={"video_id": str(v.id), "parts": [{"part_number": 1, "etag": "a"}]}
    )
    assert resp.status_code == 400 and "InvalidPart" in resp.json()["detail"]
    queues.io.enqueue.assert_not_called()


def test_complete_is_idempotent(client, user, make_video, queues):
    v = make_video(user, status=VideoStatus.uploaded)
    resp = client.post("/videos/complete", json={"video_id": str(v.id)})
    assert resp.status_code == 200
    queues.io.enqueue.assert_not_called()


def test_complete_unknown_video(client, user):
    assert client.post("/videos/complete", json={"video_id": str(uuid.uuid4())}).status_code == 404


def test_complete_is_rate_limited(client, user, make_video):
    v = make_video(user, status=VideoStatus.uploaded)
    codes = [client.post("/videos/complete", json={"video_id": str(v.id)}).status_code for _ in range(6)]
    assert codes[-1] == 429


# ---------------------------------------------------------------- abort


def test_abort_multipart_deletes_video(client, user, make_video, r2, db):
    v = multipart(make_video, user)
    vid, key = v.id, v.r2_key
    assert client.post(f"/videos/{vid}/abort").status_code == 200
    r2["abort_multipart_upload"].assert_called_once_with(key, "u1")
    assert db.query(Video).filter_by(id=vid).count() == 0


def test_abort_single_does_not_call_storage(client, user, make_video, r2, db):
    v = uploading(make_video, user, upload={"mode": "single"})
    assert client.post(f"/videos/{v.id}/abort").status_code == 200
    r2["abort_multipart_upload"].assert_not_called()


def test_abort_tolerates_already_expired_upload(client, user, make_video, r2):
    v = multipart(make_video, user)
    r2["abort_multipart_upload"].side_effect = client_error("NoSuchUpload")
    assert client.post(f"/videos/{v.id}/abort").status_code == 200


def test_abort_surfaces_other_storage_errors(client, user, make_video, r2, db):
    v = multipart(make_video, user)
    r2["abort_multipart_upload"].side_effect = client_error("InternalError")
    assert client.post(f"/videos/{v.id}/abort").status_code == 500
    assert db.get(Video, v.id) is not None


def test_abort_only_while_uploading(client, user, make_video):
    v = make_video(user, status=VideoStatus.ready)
    assert client.post(f"/videos/{v.id}/abort").status_code == 409


# ---------------------------------------------------------------- list


def test_list_groups_by_status_newest_first(client, user, make_video):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    old = make_video(user, status=VideoStatus.ready, created_at=now)
    new = make_video(user, status=VideoStatus.ready, created_at=now + timedelta(days=1))
    make_video(user, status=VideoStatus.processing)
    make_video(user, status=VideoStatus.error, pipeline={"error": "boom"})
    body = client.get("/videos/").json()
    assert [v["video_id"] for v in body["ready_videos"]] == [str(new.id), str(old.id)]
    assert len(body["processing_videos"]) == 1
    assert body["error_videos"][0]["error"] == "boom"
    assert body["uploading_videos"] == [] and body["uploaded_videos"] == []


def test_list_only_returns_own_videos(client, user, other_user, make_video):
    make_video(other_user)
    mine = make_video(user)
    body = client.get("/videos/").json()
    assert [v["video_id"] for v in body["ready_videos"]] == [str(mine.id)]


def test_list_counts_only_ready_clips(client, user, make_video, db):
    v = make_video(user)
    for status in ("ready", "ready", "queued", "error"):
        db.add(Clip(video_id=v.id, user_id=user.id, status=status, params={}))
    db.commit()
    assert client.get("/videos/").json()["ready_videos"][0]["clip_count"] == 2


def test_list_exposes_dimensions_and_retry_flag(client, user, make_video):
    make_video(
        user,
        artifacts={"width": 1920, "height": 1080},
        pipeline={"retrying": True, "stage": "transcribe", "progress_pct": 40},
    )
    item = client.get("/videos/").json()["ready_videos"][0]
    assert item["aspect_ratio"] == "16:9" and item["retrying"] is True
    assert item["stage"] == "transcribe" and item["stage_pct"] == 40


def test_list_hides_internal_upload_state(client, user, make_video):
    make_video(user, status=VideoStatus.uploading, pipeline={"upload": {"upload_id": "secret"}})
    item = client.get("/videos/").json()["uploading_videos"][0]
    assert "secret" not in str(item)


# ---------------------------------------------------------------- search


def test_search_blank_query_returns_nothing(client, user, make_video):
    make_video(user)
    assert client.get("/videos/search", params={"q": "   "}).json() == {"videos": []}


def test_search_falls_back_to_filename_match_when_embedding_fails(client, user, make_video):
    hit = make_video(user, filename="Podcast Episode 12.mp4")
    make_video(user, filename="holiday.mp4")
    ids = [v["video_id"] for v in client.get("/videos/search", params={"q": "podcast"}).json()["videos"]]
    assert ids == [str(hit.id)]


def test_search_is_scoped_to_the_user(client, user, other_user, make_video):
    make_video(other_user, filename="podcast.mp4")
    assert client.get("/videos/search", params={"q": "podcast"}).json()["videos"] == []


def test_search_no_match(client, user, make_video):
    make_video(user, filename="a.mp4")
    assert client.get("/videos/search", params={"q": "zzz"}).json()["videos"] == []


def test_search_includes_clip_counts(client, user, make_video, db):
    v = make_video(user, filename="podcast.mp4")
    db.add(Clip(video_id=v.id, user_id=user.id, status="ready", params={}))
    db.commit()
    assert client.get("/videos/search", params={"q": "pod"}).json()["videos"][0]["clip_count"] == 1


def test_search_requires_q(client, user):
    assert client.get("/videos/search").status_code == 422


def test_search_is_rate_limited(client, user):
    codes = [client.get("/videos/search", params={"q": "a"}).status_code for _ in range(31)]
    assert codes[-1] == 429


# ---------------------------------------------------------------- metadata / moments


def test_metadata(client, user, make_video):
    v = make_video(user, duration_sec=61.5, artifacts={"width": 1080, "height": 1920})
    assert client.get(f"/videos/{v.id}/metadata").json() == {
        "duration": 61.5,
        "filename": "talk.mp4",
        "width": 1080,
        "height": 1920,
        "aspect_ratio": "9:16",
    }


def test_metadata_before_ingest_has_nulls(client, user, make_video):
    v = make_video(user, duration_sec=None)
    body = client.get(f"/videos/{v.id}/metadata").json()
    assert body["duration"] is None and body["aspect_ratio"] is None


def test_metadata_rejects_malformed_id(client, user):
    assert client.get("/videos/not-a-uuid/metadata").status_code == 422


def test_moments_in_creation_order(client, user, make_video, db):
    v = make_video(user)
    run = RankingRun(video_id=v.id, prompt_version="t", model="m")
    db.add(run)
    db.commit()
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i, title in enumerate(["second", "first"]):
        db.add(
            Moment(
                video_id=v.id,
                run_id=run.id,
                start_sec=i,
                end_sec=i + 5,
                scores={"final": 5},
                title=title,
                created_at=base - timedelta(hours=i),
            )
        )
    db.commit()
    body = client.get(f"/videos/{v.id}/moments").json()
    assert [m["title"] for m in body["moments"]] == ["first", "second"]
    assert body["status"] == "ready" and body["duration"] == 600
    assert body["moments"][0]["start_sec"] == 1.0


def test_moments_empty(client, user, make_video):
    v = make_video(user, status=VideoStatus.processing)
    body = client.get(f"/videos/{v.id}/moments").json()
    assert body["moments"] == [] and body["status"] == "processing"


# ---------------------------------------------------------------- delete


def test_delete_removes_rows_and_storage(client, user, make_video, r2, db):
    v = make_video(user)
    db.add(Clip(video_id=v.id, user_id=user.id, status="ready", r2_key="clips/a.mp4", params={}))
    db.add(Clip(video_id=v.id, user_id=user.id, status="queued", r2_key=None, params={}))
    db.commit()
    vid, key = v.id, v.r2_key
    assert client.delete(f"/videos/{vid}").status_code == 200
    assert db.query(Video).filter_by(id=vid).count() == 0
    deleted = [c.args[0] for c in r2["delete_file"].call_args_list]
    assert key in deleted and "clips/a.mp4" in deleted and len(deleted) == 2
    r2["delete_prefix"].assert_called_once_with(f"artifacts/{vid}")


def test_delete_aborts_in_flight_multipart(client, user, make_video, r2):
    v = multipart(make_video, user)
    assert client.delete(f"/videos/{v.id}").status_code == 200
    r2["abort_multipart_upload"].assert_called_once()


def test_delete_keeps_the_row_if_storage_fails(client, user, make_video, r2, db):
    v = make_video(user)
    r2["delete_file"].side_effect = RuntimeError("r2 down")
    assert client.delete(f"/videos/{v.id}").status_code == 500
    assert db.get(Video, v.id) is not None


# ---------------------------------------------------------------- ownership across the whole router


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/videos/{id}/parts", {"part_numbers": [1]}),
        ("get", "/videos/{id}/upload-status", None),
        ("post", "/videos/{id}/abort", None),
        ("get", "/videos/{id}/metadata", None),
        ("get", "/videos/{id}/moments", None),
        ("delete", "/videos/{id}", None),
    ],
)
def test_every_per_video_route_hides_other_users_videos(
    client, user, other_user, make_video, r2, db, method, path, body
):
    v = make_video(
        other_user,
        status=VideoStatus.uploading,
        pipeline={"upload": {"mode": "multipart", "upload_id": "u", "part_count": 2}},
    )
    kwargs = {"json": body} if body is not None else {}
    resp = getattr(client, method)(path.format(id=v.id), **kwargs)
    assert resp.status_code == 404
    assert db.get(Video, v.id) is not None
    r2["delete_file"].assert_not_called()
    r2["abort_multipart_upload"].assert_not_called()
