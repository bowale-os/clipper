import logging

from fastapi import Depends, HTTPException, status

from app.db.models import User
from app.dependencies.user import get_current_user_record
from app.workers.queues import redis_conn

logger = logging.getLogger(__name__)

_CHECK_SCRIPT = redis_conn.register_script("""
local current = redis.call("INCR", KEYS[1])
if tonumber(current) == 1 then
    redis.call("EXPIRE", KEYS[1], ARGV[1])
    return {current, tonumber(ARGV[1])}
end
return {current, redis.call("TTL", KEYS[1])}
""")


def rate_limit(name: str, limit: int, window_seconds: int):
    """Caps `name` to `limit` calls per `window_seconds`, per user.

    Fails open on Redis errors: these routes enqueue onto the same Redis
    connection right after this check, so an outage already breaks them
    downstream regardless of what this returns.
    """
    def _check(user: User = Depends(get_current_user_record)) -> None:
        key = f"rl:{name}:{user.id}"
        try:
            current, ttl = _CHECK_SCRIPT(keys=[key], args=[window_seconds])
        except Exception:
            logger.exception("Rate limit check failed open for key=%s", key)
            return

        if current > limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded: {limit} requests per {window_seconds}s. Try again in {ttl}s.",
                headers={"Retry-After": str(ttl)},
            )

    return _check
