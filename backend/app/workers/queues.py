from redis import Redis
from rq import Queue, Retry

from app.config.secrets import settings

def redis_connection() -> Redis:
    url = settings.REDIS_URL
    if not url:
        raise RuntimeError("REDIS_URL is not set")
    return Redis.from_url(url)

redis_conn = redis_connection()
io_queue = Queue("io", connection=redis_conn, default_timeout=1800)
cpu_queue = Queue("cpu", connection=redis_conn, default_timeout=1800)

# Three retries (four attempts total), backing off 1min / 5min / 15min. The failures
# worth retrying are transient upstream ones — Gemini and Groq both return 503 under
# load — so retrying immediately just fails again while the provider is still saturated.
#
# Two things this depends on, both easy to break:
#  * every stage is idempotent (_ingest_done, _transcribe_done, _detect_done,
#    _render_done), or a retry would duplicate work it already committed;
#  * the worker runs with_scheduler=True, or delayed retries sit in RQ's
#    ScheduledJobRegistry forever and the job silently disappears. See worker_setup.py.
JOB_RETRY = Retry(max=3, interval=[60, 300, 600])