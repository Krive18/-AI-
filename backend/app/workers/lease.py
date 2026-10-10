from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass, field
from uuid import uuid4

from redis.asyncio import Redis

_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""

_RENEW_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WorkLease:
    """Renewable Redis ownership lease; MySQL remains the workflow source of truth."""

    redis: Redis
    key: str
    ttl_seconds: int
    token: str = ""
    _owner_task: asyncio.Task[object] | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _renewal_task: asyncio.Task[None] | None = field(
        default=None,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if self.ttl_seconds <= 0:
            raise ValueError("lease ttl_seconds must be positive")

    async def __aenter__(self) -> WorkLease | None:
        self.token = uuid4().hex
        acquired = await self.redis.set(
            self.key,
            self.token,
            ex=self.ttl_seconds,
            nx=True,
        )
        if not bool(acquired):
            self.token = ""
            return None

        self._owner_task = asyncio.current_task()
        self._renewal_task = asyncio.create_task(
            self._renew_until_released(),
            name=f"renew-worker-lease:{self.key}",
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        *_: object,
    ) -> None:
        renewal_task = self._renewal_task
        self._renewal_task = None
        if renewal_task is not None:
            renewal_task.cancel()
            with suppress(asyncio.CancelledError):
                await renewal_task

        token, self.token = self.token, ""
        self._owner_task = None
        if not token:
            return
        try:
            await self.redis.eval(_RELEASE_SCRIPT, 1, self.key, token)
        except Exception:
            if exc_type is None:
                raise
            logger.exception(
                "failed to release worker lease", extra={"lease_key": self.key}
            )

    async def _renew_until_released(self) -> None:
        interval = max(1.0, self.ttl_seconds / 3)
        while True:
            await asyncio.sleep(interval)
            try:
                renewed = await self.redis.eval(
                    _RENEW_SCRIPT,
                    1,
                    self.key,
                    self.token,
                    self.ttl_seconds,
                )
            except Exception:
                logger.exception(
                    "worker lease renewal failed",
                    extra={"lease_key": self.key},
                )
                renewed = 0

            if bool(renewed):
                continue

            logger.error("worker lease ownership lost", extra={"lease_key": self.key})
            owner_task = self._owner_task
            if owner_task is not None and not owner_task.done():
                owner_task.cancel(f"worker lease lost: {self.key}")
            return
