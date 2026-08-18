from datetime import datetime, timezone
from types import SimpleNamespace

from app.api.video import _aspect_ratio, _video_to_dict


def _video(
    video_id="00000000-0000-0000-0000-000000000000",
    filename="clip.mp4",
    size_bytes=1000,
    status_value="ready",
    duration_sec=None,
    content_type="video/mp4",
    created_at=None,
    pipeline=None,
    artifacts=None,
):
    return SimpleNamespace(
        id=video_id,
        filename=filename,
        size_bytes=size_bytes,
        status=SimpleNamespace(value=status_value),
        duration_sec=duration_sec,
        content_type=content_type,
        created_at=created_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
        pipeline=pipeline,
        artifacts=artifacts if artifacts is not None else {},
    )


# ---------------------------------------------------------------------------
# _aspect_ratio
# ---------------------------------------------------------------------------

def test_aspect_ratio_16_9():
    assert _aspect_ratio(1920, 1080) == "16:9"


def test_aspect_ratio_1_1():
    assert _aspect_ratio(1080, 1080) == "1:1"


def test_aspect_ratio_9_16():
    assert _aspect_ratio(1080, 1920) == "9:16"


def test_aspect_ratio_coprime_pair_unchanged():
    assert _aspect_ratio(7, 5) == "7:5"


def test_aspect_ratio_width_zero_none():
    assert _aspect_ratio(0, 1080) is None


def test_aspect_ratio_height_zero_none():
    assert _aspect_ratio(1920, 0) is None


def test_aspect_ratio_width_none():
    assert _aspect_ratio(None, 1080) is None


def test_aspect_ratio_height_none():
    assert _aspect_ratio(1920, None) is None


def test_aspect_ratio_both_none():
    assert _aspect_ratio(None, None) is None


# ---------------------------------------------------------------------------
# _video_to_dict
# ---------------------------------------------------------------------------

def test_video_to_dict_pipeline_none_defaults():
    video = _video(pipeline=None)
    result = _video_to_dict(video)
    assert result["stage"] is None
    assert result["stage_pct"] is None
    assert result["error"] is None
    assert result["retrying"] is False


def test_video_to_dict_pipeline_populated():
    video = _video(pipeline={"stage": "render", "progress_pct": 42, "error": "boom", "retrying": True})
    result = _video_to_dict(video)
    assert result["stage"] == "render"
    assert result["stage_pct"] == 42
    assert result["error"] == "boom"
    assert result["retrying"] is True


def test_video_to_dict_duration_none():
    video = _video(duration_sec=None)
    result = _video_to_dict(video)
    assert result["duration_sec"] is None


def test_video_to_dict_duration_converted_to_float():
    video = _video(duration_sec=42)
    result = _video_to_dict(video)
    assert result["duration_sec"] == 42.0
    assert isinstance(result["duration_sec"], float)


def test_video_to_dict_artifacts_missing_dimensions():
    video = _video(artifacts={})
    result = _video_to_dict(video)
    assert result["width"] is None
    assert result["height"] is None
    assert result["aspect_ratio"] is None


def test_video_to_dict_artifacts_with_dimensions():
    video = _video(artifacts={"width": 1920, "height": 1080})
    result = _video_to_dict(video)
    assert result["width"] == 1920
    assert result["height"] == 1080
    assert result["aspect_ratio"] == "16:9"


def test_video_to_dict_default_clip_count_zero():
    video = _video()
    result = _video_to_dict(video)
    assert result["clip_count"] == 0


def test_video_to_dict_explicit_clip_count_passed_through():
    video = _video()
    result = _video_to_dict(video, clip_count=7)
    assert result["clip_count"] == 7


def test_video_to_dict_status_value_surfaces():
    video = _video(status_value="processing")
    result = _video_to_dict(video)
    assert result["status"] == "processing"


def test_video_to_dict_created_at_isoformat():
    dt = datetime(2026, 3, 5, 12, 30, tzinfo=timezone.utc)
    video = _video(created_at=dt)
    result = _video_to_dict(video)
    assert result["created_at"] == dt.isoformat()
