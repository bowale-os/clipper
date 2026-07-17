from redis import Redis
from rq import Queue

from app.config.secrets import settings

def redis_connection() -> Redis:
    url = settings.REDIS_URL
    if not url:
        raise RuntimeError("REDIS_URL is not set")
    return Redis.from_url(url)

redis_conn = redis_connection()
io_queue = Queue("io", connection=redis_conn, default_timeout=1800)
cpu_queue = Queue("cpu", connection=redis_conn, default_timeout=1800)