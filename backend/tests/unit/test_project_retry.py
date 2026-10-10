from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.errors import AppError
from app.modules.account.model import AccountStatus, Role
from app.modules.account.schemas import AccountRecord
from app.modules.project.service import ProjectService
from app.modules.project.storage import LocalPrivateStorage
from app.modules.translation.model import ProjectStatus, TaskStatus


class _QueuedResult:
    def __init__(self, *, one: Any = None, rows: list[Any] | None = None) -> None:
        self._one = one
        self._rows = rows or []

    def scalar_one_or_none(self) -> Any:
        return self._one

    def scalars(self) -> list[Any]:
        return self._rows


class _QueuedSession:
    def __init__(self, results: list[_QueuedResult]) -> None:
        self._results = list(results)
        self.added: list[Any] = []
        self.commits = 0

    async def execute(self, statement: Any) -> _QueuedResult:
        return self._results.pop(0)

    def add(self, value: Any) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.commits += 1


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


def _project(**overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "id": 11,
        "status": int(ProjectStatus.FAILED),
        "progress_percent": 80,
        "cancel_requested_at": None,
        "completed_at": None,
        "updated_at": None,
        "version": 1,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _task(**overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "id": 22,
        "status": int(TaskStatus.FAILED),
        "stage": 3,
        "progress_percent": 40,
        "retry_count": 1,
        "max_retries": 3,
        "error_code": "TTS_FAILED",
        "error_message": "boom",
        "completed_at": datetime(2026, 9, 1, tzinfo=UTC).replace(tzinfo=None),
        "updated_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


async def test_retry_rejects_task_that_reached_max_retries(tmp_path: Path) -> None:
    session = _QueuedSession(
        [
            _QueuedResult(one=_project()),
            _QueuedResult(one=_task(retry_count=3, max_retries=3)),
        ]
    )
    service = _service(session, tmp_path)

    with pytest.raises(AppError) as error:
        await service.retry(_account(), "project-1", "task-1")

    assert error.value.code == "TASK_RETRY_LIMIT"
    assert error.value.status_code == 409
    assert session.commits == 0


async def test_retry_resets_failed_task_below_max_retries(tmp_path: Path) -> None:
    project = _project()
    task = _task(retry_count=1, max_retries=3)
    session = _QueuedSession([_QueuedResult(one=project), _QueuedResult(one=task)])
    service = _service(session, tmp_path)

    result = await service.retry(_account(), "project-1", "task-1")

    assert result is task
    assert task.status == int(TaskStatus.QUEUED)
    assert task.stage == 1
    assert task.progress_percent == 0
    assert task.error_code is None
    assert task.retry_count == 2
    assert project.status == int(ProjectStatus.PROCESSING)
    assert project.version == 2
    assert session.commits == 1


async def test_retry_project_skips_tasks_at_max_retries(tmp_path: Path) -> None:
    project = _project(status=int(ProjectStatus.PARTIALLY_SUCCEEDED))
    limited = _task(id=22, retry_count=3, max_retries=3)
    retryable = _task(id=23, retry_count=0, max_retries=3)
    succeeded = _task(id=24, status=int(TaskStatus.SUCCEEDED))
    session = _QueuedSession(
        [
            _QueuedResult(one=project),
            _QueuedResult(rows=[limited, retryable, succeeded]),
        ]
    )
    service = _service(session, tmp_path)

    await service.retry_project(_account(), "project-1")

    assert limited.status == int(TaskStatus.FAILED)
    assert limited.retry_count == 3
    assert retryable.status == int(TaskStatus.QUEUED)
    assert retryable.retry_count == 1
    assert succeeded.status == int(TaskStatus.SUCCEEDED)
    assert project.status == int(ProjectStatus.VALIDATING)
    assert session.commits == 1


async def test_retry_project_rejects_when_all_failed_tasks_hit_limit(
    tmp_path: Path,
) -> None:
    project = _project()
    limited = _task(retry_count=3, max_retries=3)
    session = _QueuedSession(
        [_QueuedResult(one=project), _QueuedResult(rows=[limited])]
    )
    service = _service(session, tmp_path)

    with pytest.raises(AppError) as error:
        await service.retry_project(_account(), "project-1")

    assert error.value.code == "PROJECT_RETRY_LIMIT"
    assert error.value.status_code == 400
    assert session.commits == 0
