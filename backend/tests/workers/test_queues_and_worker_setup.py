from unittest.mock import MagicMock

import pytest

import app.workers.queues as queues
import app.workers.worker_setup as worker_setup


def test_queue_names_and_timeouts():
    assert queues.io_queue.name == "io" and queues.cpu_queue.name == "cpu"
    assert queues.io_queue._default_timeout == 1800
    assert queues.cpu_queue._default_timeout == 1800


def test_retry_policy_backs_off_three_times():
    assert queues.JOB_RETRY.max == 3
    assert queues.JOB_RETRY.intervals == [60, 300, 600]


def test_redis_connection_requires_a_url(monkeypatch):
    monkeypatch.setattr(queues.settings, "REDIS_URL", "")
    with pytest.raises(RuntimeError, match="REDIS_URL"):
        queues.redis_connection()


def test_redis_connection_uses_the_configured_url(monkeypatch):
    monkeypatch.setattr(queues.settings, "REDIS_URL", "redis://example.invalid:6380/3")
    kwargs = queues.redis_connection().connection_pool.connection_kwargs
    assert kwargs["host"] == "example.invalid" and kwargs["port"] == 6380 and kwargs["db"] == 3


# ---------------------------------------------------------------- worker queue selection


def test_default_worker_drains_both_queues_render_first(monkeypatch):
    monkeypatch.delenv("WORKER_QUEUES", raising=False)
    assert [q.name for q in worker_setup._selected_queues()] == ["cpu", "io"]


@pytest.mark.parametrize(
    "value,expected",
    [("cpu", ["cpu"]), ("io", ["io"]), ("io,cpu", ["io", "cpu"]), (" cpu , io ", ["cpu", "io"]), ("cpu,,io,", ["cpu", "io"])],
)
def test_worker_queue_selection(monkeypatch, value, expected):
    monkeypatch.setenv("WORKER_QUEUES", value)
    assert [q.name for q in worker_setup._selected_queues()] == expected


def test_unknown_queue_name_fails_loudly(monkeypatch):
    monkeypatch.setenv("WORKER_QUEUES", "cpu,gpu")
    with pytest.raises(RuntimeError, match="gpu"):
        worker_setup._selected_queues()


def test_main_starts_the_worker_with_the_scheduler(monkeypatch):
    worker_class = MagicMock(__name__="FakeWorker")
    fake_queues = [MagicMock(), MagicMock()]
    fake_queues[0].name, fake_queues[1].name = "q1", "q2"
    monkeypatch.setattr(worker_setup, "WorkerClass", worker_class)
    monkeypatch.setattr(worker_setup, "QUEUES", fake_queues)
    worker_setup.main()
    worker_class.assert_called_once_with(fake_queues, connection=worker_setup.redis_conn)
    # Without the scheduler, jobs waiting out a retry backoff would silently vanish.
    worker_class.return_value.work.assert_called_once_with(with_scheduler=True)
