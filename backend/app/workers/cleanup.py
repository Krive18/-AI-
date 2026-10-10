from __future__ import annotations

import json
import logging
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.translation.model import TranslationProject

logger = logging.getLogger(__name__)

_ORPHAN_UPLOAD_AGE = timedelta(hours=24)
_IDEMPOTENCY_AGE = timedelta(days=7)


async def sweep_private_storage(
    root: Path,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    """Best-effort garbage collection for the local private storage root."""
    current = now or datetime.now(UTC)
    now_ts = current.timestamp()
    counts = {"sessions": 0, "uploads": 0, "idempotency": 0, "skipped": 0}
    referenced = await _referenced_source_keys(session_factory)
    _sweep_sessions(root, now_ts, referenced, counts)
    _sweep_uploads(root, now_ts, referenced, counts)
    _sweep_idempotency(root, now_ts, counts)
    logger.info("private storage sweep finished: %s", counts)
    return counts


async def _referenced_source_keys(
    session_factory: async_sessionmaker[AsyncSession],
) -> set[str]:
    async with session_factory() as session:
        rows = await session.execute(select(TranslationProject.source_object_key))
        return {str(key) for key in rows.scalars()}


def _sweep_sessions(
    root: Path, now_ts: float, referenced: set[str], counts: dict[str, int]
) -> None:
    directory = root / "sessions"
    if not directory.is_dir():
        return
    for path in directory.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            expires_at = int(str(payload.get("expiresAt", 0)))
            account_id = int(str(payload["accountId"]))
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            counts["skipped"] += 1
            continue
        if expires_at >= int(now_ts):
            continue
        try:
            path.unlink()
        except OSError:
            counts["skipped"] += 1
            continue
        counts["sessions"] += 1
        upload_key = f"uploads/{account_id}/{path.stem}/source"
        upload_dir = root / "uploads" / str(account_id) / path.stem
        # A consumed upload may back a project source; never delete those.
        if upload_key in referenced or not upload_dir.is_dir():
            continue
        try:
            shutil.rmtree(upload_dir)
            counts["uploads"] += 1
        except OSError:
            counts["skipped"] += 1


def _sweep_uploads(
    root: Path, now_ts: float, referenced: set[str], counts: dict[str, int]
) -> None:
    directory = root / "uploads"
    if not directory.is_dir():
        return
    for account_dir in directory.iterdir():
        if not account_dir.is_dir():
            continue
        for upload_dir in account_dir.iterdir():
            if not upload_dir.is_dir():
                continue
            key = f"uploads/{account_dir.name}/{upload_dir.name}/source"
            if key in referenced:
                continue
            try:
                age = now_ts - _newest_mtime(upload_dir)
            except OSError:
                counts["skipped"] += 1
                continue
            if age < _ORPHAN_UPLOAD_AGE.total_seconds():
                continue
            try:
                shutil.rmtree(upload_dir)
                counts["uploads"] += 1
            except OSError:
                counts["skipped"] += 1


def _sweep_idempotency(root: Path, now_ts: float, counts: dict[str, int]) -> None:
    directory = root / "idempotency"
    if not directory.is_dir():
        return
    for path in directory.glob("*/*.json"):
        try:
            age = now_ts - path.stat().st_mtime
        except OSError:
            counts["skipped"] += 1
            continue
        if age < _IDEMPOTENCY_AGE.total_seconds():
            continue
        try:
            path.unlink()
            counts["idempotency"] += 1
        except OSError:
            counts["skipped"] += 1


def _newest_mtime(directory: Path) -> float:
    newest = directory.stat().st_mtime
    for path in directory.rglob("*"):
        newest = max(newest, path.stat().st_mtime)
    return newest
