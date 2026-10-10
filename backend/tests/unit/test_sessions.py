from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.modules.auth.sessions import SessionStore


class FakeClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value

    def advance(self, **delta: int) -> None:
        self.value += timedelta(**delta)


class FakePipeline:
    def __init__(self, redis: FakeRedis) -> None:
        self._redis = redis
        self._commands: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def set(self, *args: Any, **kwargs: Any) -> FakePipeline:
        self._commands.append(("set", args, kwargs))
        return self

    def sadd(self, *args: Any, **kwargs: Any) -> FakePipeline:
        self._commands.append(("sadd", args, kwargs))
        return self

    def expire(self, *args: Any, **kwargs: Any) -> FakePipeline:
        self._commands.append(("expire", args, kwargs))
        return self

    def delete(self, *args: Any, **kwargs: Any) -> FakePipeline:
        self._commands.append(("delete", args, kwargs))
        return self

    def srem(self, *args: Any, **kwargs: Any) -> FakePipeline:
        self._commands.append(("srem", args, kwargs))
        return self

    async def execute(self) -> list[object]:
        result: list[object] = []
        for method, args, kwargs in self._commands:
            result.append(await getattr(self._redis, method)(*args, **kwargs))
        return result


class FakeRedis:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.values: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}
        self.expires_at: dict[str, datetime] = {}

    def _purge(self, key: str) -> None:
        expires_at = self.expires_at.get(key)
        if expires_at is not None and expires_at <= self.clock.now():
            self.values.pop(key, None)
            self.sets.pop(key, None)
            self.expires_at.pop(key, None)

    async def get(self, key: str) -> str | None:
        self._purge(key)
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ex: int | None = None) -> bool:
        self.values[key] = value
        self.sets.pop(key, None)
        if ex is not None:
            self.expires_at[key] = self.clock.now() + timedelta(seconds=ex)
        else:
            self.expires_at.pop(key, None)
        return True

    async def expire(self, key: str, seconds: int) -> bool:
        self._purge(key)
        if key not in self.values and key not in self.sets:
            return False
        self.expires_at[key] = self.clock.now() + timedelta(seconds=seconds)
        return True

    async def ttl(self, key: str) -> int:
        self._purge(key)
        if key not in self.values and key not in self.sets:
            return -2
        expires_at = self.expires_at.get(key)
        if expires_at is None:
            return -1
        return max(0, int((expires_at - self.clock.now()).total_seconds()))

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            self._purge(key)
            existed = key in self.values or key in self.sets
            self.values.pop(key, None)
            self.sets.pop(key, None)
            self.expires_at.pop(key, None)
            deleted += int(existed)
        return deleted

    async def sadd(self, key: str, *values: str) -> int:
        self._purge(key)
        members = self.sets.setdefault(key, set())
        self.values.pop(key, None)
        before = len(members)
        members.update(values)
        return len(members) - before

    async def smembers(self, key: str) -> set[str]:
        self._purge(key)
        return set(self.sets.get(key, set()))

    async def srem(self, key: str, *values: str) -> int:
        self._purge(key)
        members = self.sets.get(key)
        if members is None:
            return 0
        removed = sum(value in members for value in values)
        members.difference_update(values)
        return removed

    def pipeline(self, *, transaction: bool = True) -> FakePipeline:
        assert transaction
        return FakePipeline(self)

    async def eval(self, script: str, numkeys: int, *args: str) -> int:
        assert numkeys == 1
        assert "SMEMBERS" in script
        index_key, session_prefix = args
        members = await self.smembers(index_key)
        await self.delete(*(f"{session_prefix}{member}" for member in members))
        return await self.delete(index_key)

    async def scan_iter(self, match: str) -> AsyncIterator[str]:
        prefix = match.rstrip("*")
        for key in tuple(self.values | self.sets):
            self._purge(key)
            if key.startswith(prefix):
                yield key


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def fake_redis(clock: FakeClock) -> FakeRedis:
    return FakeRedis(clock)


@pytest.fixture
def session_store(clock: FakeClock, fake_redis: FakeRedis) -> SessionStore:
    return SessionStore(
        redis=fake_redis,
        session_hash_key="unit-test-session-hash-key-that-is-at-least-32-bytes",
        clock=clock.now,
        key_prefix="test-session:",
    )


async def test_session_touch_never_exceeds_absolute_expiry(
    clock: FakeClock, session_store: SessionStore
) -> None:
    token, created = await session_store.create(account_id=17, auth_version=3)
    assert await session_store.ttl(token) == 8 * 60 * 60

    clock.advance(hours=7, minutes=50)
    assert await session_store.get_and_touch(token) is not None
    clock.advance(hours=7, minutes=50)
    assert await session_store.get_and_touch(token) is not None
    clock.advance(hours=7, minutes=50)
    loaded = await session_store.get_and_touch(token)

    assert loaded is not None
    assert loaded.account_id == 17
    assert loaded.absolute_expires_at == created.absolute_expires_at
    assert await session_store.ttl(token) <= 30 * 60


async def test_session_keys_do_not_contain_raw_token_or_payload(
    session_store: SessionStore, fake_redis: FakeRedis
) -> None:
    token, _ = await session_store.create(account_id=23, auth_version=1)

    keys = tuple(fake_redis.values | fake_redis.sets)

    assert token not in " ".join(keys)
    session_keys = [key for key in keys if ":session:" in key]
    assert len(session_keys) == 1
    assert re.fullmatch(r"test-session:session:[0-9a-f]{64}", session_keys[0])


async def test_revoke_account_removes_every_active_session(
    session_store: SessionStore,
) -> None:
    first, _ = await session_store.create(account_id=29, auth_version=1)
    second, _ = await session_store.create(account_id=29, auth_version=1)

    await session_store.revoke_account(29)

    assert await session_store.get_and_touch(first) is None
    assert await session_store.get_and_touch(second) is None


async def test_corrupt_session_data_is_invalidated_without_leaking_payload(
    session_store: SessionStore, fake_redis: FakeRedis
) -> None:
    token, _ = await session_store.create(account_id=31, auth_version=1)
    session_key = next(key for key in fake_redis.values if ":session:" in key)
    await fake_redis.set(session_key, "not-json", ex=60)

    assert await session_store.get_and_touch(token) is None
