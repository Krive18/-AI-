from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Self

from app.workers.cleanup import sweep_private_storage

_NOW = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)


class _KeysResult:
    def __init__(self, keys: list[str]) -> None:
        self._keys = keys

    def scalars(self) -> list[str]:
        return self._keys


class _FakeSession:
    def __init__(self, keys: list[str]) -> None:
        self._keys = keys

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def execute(self, statement: Any) -> _KeysResult:
        return _KeysResult(self._keys)


class _FakeSessionFactory:
    def __init__(self, keys: list[str]) -> None:
        self._keys = keys

    def __call__(self) -> _FakeSession:
        return _FakeSession(self._keys)


def _write_session(root: Path, token: str, account_id: int, expires_at: int) -> Path:
    directory = root / "sessions"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{token}.json"
    path.write_text(
        json.dumps(
            {
                "accountId": account_id,
                "filename": "source.mp4",
                "contentType": "video/mp4",
                "totalBytes": 10,
                "objectKey": f"uploads/{account_id}/{token}/source",
                "expiresAt": expires_at,
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_upload(root: Path, account_id: int, token: str, age: timedelta) -> Path:
    directory = root / "uploads" / str(account_id) / token
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "source"
    source.write_bytes(b"video")
    moment = (_NOW - age).timestamp()
    os.utime(source, (moment, moment))
    os.utime(directory, (moment, moment))
    return directory


def _write_idempotency(root: Path, name: str, age: timedelta) -> Path:
    directory = root / "idempotency" / "7"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.json"
    path.write_text(json.dumps({"projectId": "p1"}), encoding="utf-8")
    moment = (_NOW - age).timestamp()
    os.utime(path, (moment, moment))
    return path


async def test_sweep_deletes_expired_session_and_its_upload_dir(
    tmp_path: Path,
) -> None:
    expired = _NOW - timedelta(hours=1)
    session_path = _write_session(tmp_path, "tok-old", 7, int(expired.timestamp()))
    upload_dir = _write_upload(tmp_path, 7, "tok-old", timedelta(hours=1))
    factory = _FakeSessionFactory([])

    counts = await sweep_private_storage(
        tmp_path,
        factory,
        now=_NOW,  # type: ignore[arg-type]
    )

    assert not session_path.exists()
    assert not upload_dir.exists()
    assert counts["sessions"] == 1
    assert counts["uploads"] == 1
    assert counts["skipped"] == 0


async def test_sweep_keeps_unexpired_session_and_upload(tmp_path: Path) -> None:
    valid = _NOW + timedelta(hours=1)
    session_path = _write_session(tmp_path, "tok-new", 7, int(valid.timestamp()))
    upload_dir = _write_upload(tmp_path, 7, "tok-new", timedelta(hours=1))
    factory = _FakeSessionFactory([])

    counts = await sweep_private_storage(
        tmp_path,
        factory,
        now=_NOW,  # type: ignore[arg-type]
    )

    assert session_path.exists()
    assert upload_dir.exists()
    assert counts == {"sessions": 0, "uploads": 0, "idempotency": 0, "skipped": 0}


async def test_sweep_deletes_orphan_upload_older_than_a_day(tmp_path: Path) -> None:
    orphan = _write_upload(tmp_path, 7, "tok-orphan", timedelta(hours=25))
    factory = _FakeSessionFactory([])

    counts = await sweep_private_storage(
        tmp_path,
        factory,
        now=_NOW,  # type: ignore[arg-type]
    )

    assert not orphan.exists()
    assert counts["uploads"] == 1


async def test_sweep_keeps_recent_orphan_and_referenced_uploads(
    tmp_path: Path,
) -> None:
    recent = _write_upload(tmp_path, 7, "tok-recent", timedelta(hours=2))
    referenced = _write_upload(tmp_path, 7, "tok-used", timedelta(days=30))
    factory = _FakeSessionFactory(["uploads/7/tok-used/source"])

    counts = await sweep_private_storage(
        tmp_path,
        factory,
        now=_NOW,  # type: ignore[arg-type]
    )

    assert recent.exists()
    assert referenced.exists()
    assert counts["uploads"] == 0


async def test_sweep_splits_idempotency_records_by_age(tmp_path: Path) -> None:
    old = _write_idempotency(tmp_path, "old", timedelta(days=8))
    fresh = _write_idempotency(tmp_path, "fresh", timedelta(days=1))
    factory = _FakeSessionFactory([])

    counts = await sweep_private_storage(
        tmp_path,
        factory,
        now=_NOW,  # type: ignore[arg-type]
    )

    assert not old.exists()
    assert fresh.exists()
    assert counts["idempotency"] == 1
    assert counts["skipped"] == 0


async def test_sweep_skips_unparseable_session_file(tmp_path: Path) -> None:
    directory = tmp_path / "sessions"
    directory.mkdir(parents=True)
    broken = directory / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    factory = _FakeSessionFactory([])

    counts = await sweep_private_storage(
        tmp_path,
        factory,
        now=_NOW,  # type: ignore[arg-type]
    )

    assert broken.exists()
    assert counts["sessions"] == 0
    assert counts["skipped"] == 1
