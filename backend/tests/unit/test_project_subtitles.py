from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.errors import AppError
from app.modules.account.model import AccountStatus, Role
from app.modules.account.schemas import AccountRecord
from app.modules.project.routes import _srt_to_vtt
from app.modules.project.service import ProjectService
from app.modules.project.storage import LocalPrivateStorage


class _QueuedResult:
    def __init__(self, *, one: Any = None, rows: list[Any] | None = None) -> None:
        self._one = one
        self._rows = rows or []

    def scalar_one_or_none(self) -> Any:
        return self._one

    def all(self) -> list[Any]:
        return self._rows


class _QueuedSession:
    def __init__(self, results: list[_QueuedResult]) -> None:
        self._results = list(results)

    async def execute(self, statement: Any) -> _QueuedResult:
        return self._results.pop(0)


def _account() -> AccountRecord:
    now = datetime(2026, 9, 1, tzinfo=UTC).replace(tzinfo=None)
    return AccountRecord(
        id=1,
        public_id="01JTESTACCOUNT0000000000001",
        login_name="operator",
        display_name="Operator",
        role=Role.OPERATOR,
        status=AccountStatus.ACTIVE,
        password_hash="x",
        must_change_password=False,
        videogen_enabled=False,
        password_changed_at=None,
        last_login_at=None,
        created_by=None,
        auth_version=1,
        version=1,
        created_at=now,
        updated_at=now,
    )


def _service(session: _QueuedSession, tmp_path: Path) -> ProjectService:
    return ProjectService(
        session=session,  # type: ignore[arg-type]
        storage=LocalPrivateStorage(tmp_path),
    )


async def test_get_task_subtitles_joins_cleans_and_orders_segments(
    tmp_path: Path,
) -> None:
    project = SimpleNamespace(id=11)
    task = SimpleNamespace(id=22)
    rows = [
        (
            SimpleNamespace(source_text="  你好，世界  ", start_ms=1000, end_ms=3500),
            SimpleNamespace(translated_text="**Hello**   world"),
        ),
        (
            SimpleNamespace(source_text="第二句", start_ms=4000, end_ms=6000),
            SimpleNamespace(translated_text="*second* line"),
        ),
    ]
    session = _QueuedSession(
        [_QueuedResult(one=project), _QueuedResult(one=task), _QueuedResult(rows=rows)]
    )
    service = _service(session, tmp_path)

    result = await service.get_task_subtitles(_account(), "project-1", "task-1")

    assert result.segment_count == 2
    assert (
        result.source_text
        == "[00:00:01.000 --> 00:00:03.500] 你好，世界\n[00:00:04.000 --> 00:00:06.000] 第二句"
    )
    assert (
        result.target_text
        == "[00:00:01.000 --> 00:00:03.500] Hello world\n[00:00:04.000 --> 00:00:06.000] second line"
    )


async def test_get_task_subtitles_returns_empty_when_task_has_no_segments(
    tmp_path: Path,
) -> None:
    project = SimpleNamespace(id=11)
    task = SimpleNamespace(id=22)
    session = _QueuedSession(
        [_QueuedResult(one=project), _QueuedResult(one=task), _QueuedResult(rows=[])]
    )
    service = _service(session, tmp_path)

    result = await service.get_task_subtitles(_account(), "project-1", "task-1")

    assert result.segment_count == 0
    assert result.source_text == ""
    assert result.target_text == ""


async def test_get_task_subtitles_raises_not_found_for_unknown_task(
    tmp_path: Path,
) -> None:
    project = SimpleNamespace(id=11)
    session = _QueuedSession([_QueuedResult(one=project), _QueuedResult(one=None)])
    service = _service(session, tmp_path)

    with pytest.raises(AppError) as error:
        await service.get_task_subtitles(_account(), "project-1", "missing-task")

    assert error.value.code == "TASK_NOT_FOUND"
    assert error.value.status_code == 404


def test_srt_to_vtt_strips_bom_and_cue_numbers_and_converts_timestamps() -> None:
    srt = (
        "\ufeff1\n"
        "00:00:01,000 --> 00:00:03,500\n"
        "Hello, world\n"
        "\n"
        "2\n"
        "00:00:04,000 --> 00:00:06,000\n"
        "第二句，字幕\n"
    ).encode("utf-8")

    vtt = _srt_to_vtt(srt)

    assert vtt.startswith("WEBVTT\n\n")
    assert "1\n" not in vtt
    assert "00:00:01.000 --> 00:00:03.500" in vtt
    assert "00:00:04.000 --> 00:00:06.000" in vtt
    # Commas inside cue text are left untouched.
    assert "Hello, world" in vtt
    assert "第二句，字幕" in vtt
    assert "\ufeff" not in vtt
