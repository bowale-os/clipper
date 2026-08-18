from types import SimpleNamespace

import pytest

from app.workers.contract import ReadOnlyVideo, _clear_video_retrying, _will_retry


# ---------------------------------------------------------------------------
# _will_retry
# ---------------------------------------------------------------------------

def test_will_retry_none_job():
    assert _will_retry(None) is False


def test_will_retry_retries_left_zero():
    assert _will_retry(SimpleNamespace(retries_left=0)) is False


def test_will_retry_retries_left_none():
    assert _will_retry(SimpleNamespace(retries_left=None)) is False


def test_will_retry_retries_left_one():
    assert _will_retry(SimpleNamespace(retries_left=1)) is True


def test_will_retry_retries_left_three():
    assert _will_retry(SimpleNamespace(retries_left=3)) is True


# ---------------------------------------------------------------------------
# _clear_video_retrying
# ---------------------------------------------------------------------------

def test_clear_video_retrying_pipeline_none_stays_none():
    video = SimpleNamespace(pipeline=None)
    _clear_video_retrying(video)
    assert video.pipeline is None


def test_clear_video_retrying_pipeline_without_key_untouched():
    original = {"stage": "ingest"}
    video = SimpleNamespace(pipeline=original)
    _clear_video_retrying(video)
    assert video.pipeline is original  # not reassigned, since "retrying" wasn't present


def test_clear_video_retrying_removes_key_preserves_others():
    video = SimpleNamespace(pipeline={"retrying": True, "stage": "ingest"})
    _clear_video_retrying(video)
    assert video.pipeline == {"stage": "ingest"}


def test_clear_video_retrying_reassigns_new_dict_object():
    original = {"retrying": True, "stage": "ingest"}
    video = SimpleNamespace(pipeline=original)
    _clear_video_retrying(video)
    assert video.pipeline is not original


# ---------------------------------------------------------------------------
# ReadOnlyVideo
# ---------------------------------------------------------------------------

def test_read_only_video_proxies_reads():
    inner = SimpleNamespace(id="abc", pipeline={"stage": "ingest"})
    ro = ReadOnlyVideo(inner)
    assert ro.id == "abc"
    assert ro.pipeline == {"stage": "ingest"}


def test_read_only_video_missing_attribute_propagates():
    inner = SimpleNamespace(id="abc")
    ro = ReadOnlyVideo(inner)
    with pytest.raises(AttributeError):
        ro.does_not_exist


def test_read_only_video_setattr_raises():
    inner = SimpleNamespace(pipeline={})
    ro = ReadOnlyVideo(inner)
    with pytest.raises(AttributeError) as exc_info:
        ro.pipeline = {"stage": "render"}
    assert "pipeline" in str(exc_info.value)
    assert "read-only" in str(exc_info.value)


def test_read_only_video_repr_includes_wrapped_repr():
    inner = SimpleNamespace(id="abc")
    ro = ReadOnlyVideo(inner)
    assert repr(inner) in repr(ro)


def test_read_only_video_construction_succeeds():
    inner = SimpleNamespace(id="abc")
    ro = ReadOnlyVideo(inner)
    assert isinstance(ro, ReadOnlyVideo)
