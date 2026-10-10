from __future__ import annotations

import builtins
import hashlib
import hmac
import json
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, Self, cast

_IDLE_TTL = timedelta(hours=8)
_ABSOLUTE_TTL = timedelta(hours=24)
_REVOKE_ACCOUNT_LUA = """
local digests = redis.call('SMEMBERS', KEYS[1])
for _, digest in ipairs(digests) do
    redis.call('DEL', ARGV[1] .. digest)
end
return redis.call('DEL', KEYS[1])
"""


class RedisPipeline(Protocol):
    def set(self, key: str, value: str, *, ex: int) -> Self: ...

    def sadd(self, key: str, *values: str) -> Self: ...

    def expire(self, key: str, seconds: int) -> Self: ...

    def delete(self, *keys: str) -> Self: ...

    def srem(self, key: str, *values: str) -> Self: ...

    def execute(self) -> Awaitable[object]: ...


class SessionRedis(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, *, ex: int) -> object: ...

    async def ttl(self, key: str) -> int: ...

    async def delete(self, *keys: str) -> object: ...

    async def sadd(self, key: str, *values: str) -> object: ...

    async def smembers(self, key: str) -> builtins.set[str]: ...

    async def srem(self, key: str, *values: str) -> object: ...

    def pipeline(self, *, transaction: bool = True) -> RedisPipeline: ...

    async def eval(self, script: str, numkeys: int, *args: str) -> object: ...


@dataclass(frozen=True, slots=True)
class SessionData:
    account_id: int
    auth_version: int
    csrf_token: str
    created_at: datetime
    absolute_expires_at: datetime


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SessionStore:
    def __init__(
        self,
        redis: SessionRedis,
        session_hash_key: str,
        *,
        clock: Callable[[], datetime] = _utc_now,
        key_prefix: str = "",
    ) -> None:
        self._redis = redis
        self._hash_key = session_hash_key.encode()
        self._clock = clock
        self._key_prefix = key_prefix

    async def create(
        self, *, account_id: int, auth_version: int
    ) -> tuple[str, SessionData]:
        now = self._now()
        session = SessionData(
            account_id=account_id,
            auth_version=auth_version,
            csrf_token=secrets.token_urlsafe(32),
            created_at=now,
            absolute_expires_at=now + _ABSOLUTE_TTL,
        )
        token = secrets.token_urlsafe(32)
        digest = self._digest(token)
        pipeline = self._redis.pipeline(transaction=True)
        pipeline.set(
            self._session_key(digest),
            self._encode(session),
            ex=int(_IDLE_TTL.total_seconds()),
        )
        pipeline.sadd(self._account_sessions_key(account_id), digest)
        pipeline.expire(
            self._account_sessions_key(account_id), int(_ABSOLUTE_TTL.total_seconds())
        )
        await pipeline.execute()
        return token, session

    async def get_and_touch(self, token: str) -> SessionData | None:
        digest = self._digest(token)
        key = self._session_key(digest)
        raw = await self._redis.get(key)
        if raw is None:
            return None
        session = self._decode(raw)
        if session is None or session.absolute_expires_at <= self._now():
            await self._delete_session(digest, session.account_id if session else None)
            return None

        remaining = int((session.absolute_expires_at - self._now()).total_seconds())
        if remaining <= 0:
            await self._delete_session(digest, session.account_id)
            return None
        ttl = min(int(_IDLE_TTL.total_seconds()), remaining)
        pipeline = self._redis.pipeline(transaction=True)
        pipeline.expire(key, ttl)
        await pipeline.execute()
        return session

    async def revoke(self, token: str) -> None:
        digest = self._digest(token)
        raw = await self._redis.get(self._session_key(digest))
        session = self._decode(raw) if raw is not None else None
        await self._delete_session(digest, session.account_id if session else None)

    async def revoke_account(self, account_id: int) -> None:
        index_key = self._account_sessions_key(account_id)
        await self._redis.eval(
            _REVOKE_ACCOUNT_LUA,
            1,
            index_key,
            self._session_key_prefix(),
        )

    async def ttl(self, token: str) -> int:
        return await self._redis.ttl(self._session_key(self._digest(token)))

    async def _delete_session(self, digest: str, account_id: int | None) -> None:
        pipeline = self._redis.pipeline(transaction=True)
        pipeline.delete(self._session_key(digest))
        if account_id is not None:
            pipeline.srem(self._account_sessions_key(account_id), digest)
        await pipeline.execute()

    def _now(self) -> datetime:
        now = self._clock()
        return now if now.tzinfo is not None else now.replace(tzinfo=UTC)

    def _digest(self, token: str) -> str:
        return hmac.new(self._hash_key, token.encode(), hashlib.sha256).hexdigest()

    def _session_key_prefix(self) -> str:
        return f"{self._key_prefix}session:"

    def _session_key(self, digest: str) -> str:
        return f"{self._session_key_prefix()}{digest}"

    def _account_sessions_key(self, account_id: int) -> str:
        return f"{self._key_prefix}account-sessions:{account_id}"

    @staticmethod
    def _encode(session: SessionData) -> str:
        return json.dumps(
            {
                "accountId": session.account_id,
                "authVersion": session.auth_version,
                "csrfToken": session.csrf_token,
                "createdAt": session.created_at.isoformat(),
                "absoluteExpiresAt": session.absolute_expires_at.isoformat(),
            },
            separators=(",", ":"),
        )

    @staticmethod
    def _decode(raw: str) -> SessionData | None:
        try:
            value = cast(dict[str, object], json.loads(raw))
            account_id = value["accountId"]
            auth_version = value["authVersion"]
            csrf_token = value["csrfToken"]
            created_at = datetime.fromisoformat(str(value["createdAt"]))
            absolute_expires_at = datetime.fromisoformat(
                str(value["absoluteExpiresAt"])
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if (
            type(account_id) is not int
            or type(auth_version) is not int
            or not isinstance(csrf_token, str)
            or not csrf_token
        ):
            return None
        if created_at.tzinfo is None or absolute_expires_at.tzinfo is None:
            return None
        return SessionData(
            account_id=account_id,
            auth_version=auth_version,
            csrf_token=csrf_token,
            created_at=created_at.astimezone(UTC),
            absolute_expires_at=absolute_expires_at.astimezone(UTC),
        )
