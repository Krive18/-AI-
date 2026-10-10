from pathlib import Path
from typing import Any

from app.modules.project.repository import ProjectRepository
from app.modules.project.service import PROJECT_STATE_STATUSES, ProjectService
from app.modules.project.storage import LocalPrivateStorage
from app.modules.translation.model import ProjectStatus


class _ScalarResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> list[Any]:
        return self._rows


class _CaptureSession:
    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> _ScalarResult:
        self.statements.append(statement)
        return _ScalarResult([])


def _repository(session: _CaptureSession) -> ProjectRepository:
    return ProjectRepository(session=session)  # type: ignore[arg-type]


def _service(session: _CaptureSession, tmp_path: Path) -> ProjectService:
    return ProjectService(
        session=session,  # type: ignore[arg-type]
        storage=LocalPrivateStorage(tmp_path),
    )


def _compiled_params(statement: Any) -> list[Any]:
    return list(statement.compile().params.values())


async def test_list_page_without_filters_keeps_owner_cursor_and_order() -> None:
    session = _CaptureSession()

    await _repository(session).list_page(7, False, 42, 20)

    sql = str(session.statements[0])
    assert "ORDER BY translation_project.id DESC" in sql
    assert "translation_project.created_by = " in sql
    assert "translation_project.id < " in sql
    assert "LIKE" not in sql
    assert " IN " not in sql


async def test_list_page_keyword_escapes_like_wildcards_and_matches_name_or_filename() -> (
    None
):
    session = _CaptureSession()

    await _repository(session).list_page(7, True, None, 20, keyword="50%_稿")

    statement = session.statements[0]
    sql = str(statement)
    assert "translation_project.name LIKE " in sql
    assert "translation_project.source_filename LIKE " in sql
    assert " OR " in sql
    assert "ESCAPE" in sql
    # Wildcards in user input are escaped, the wrapping ones are not.
    assert r"%50\%\_稿%" in _compiled_params(statement)


async def test_list_page_statuses_adds_in_clause() -> None:
    session = _CaptureSession()

    await _repository(session).list_page(7, True, None, 20, statuses=[7, 8])

    statement = session.statements[0]
    assert "translation_project.status IN " in str(statement)
    assert [7, 8] in _compiled_params(statement)


async def test_service_maps_state_buckets_and_normalizes_empty_keyword(
    tmp_path: Path,
) -> None:
    session = _CaptureSession()

    await _service(session, tmp_path).list_page(
        7, True, None, 20, keyword="   ", state="succeeded"
    )

    statement = session.statements[0]
    assert [7, 8] in _compiled_params(statement)
    assert not [
        value for value in _compiled_params(statement) if isinstance(value, str)
    ]


async def test_service_passes_keyword_through_and_defaults_to_all_states(
    tmp_path: Path,
) -> None:
    session = _CaptureSession()

    await _service(session, tmp_path).list_page(7, True, None, 20, keyword="发布会")

    statement = session.statements[0]
    assert "%发布会%" in _compiled_params(statement)
    assert "translation_project.status IN " not in str(statement)


def test_state_buckets_cover_every_project_status_once() -> None:
    covered = [
        status for bucket in PROJECT_STATE_STATUSES.values() for status in bucket
    ]

    assert sorted(int(status) for status in covered) == [
        int(status) for status in ProjectStatus
    ]
    assert PROJECT_STATE_STATUSES["succeeded"] == (
        ProjectStatus.SUCCEEDED,
        ProjectStatus.PARTIALLY_SUCCEEDED,
    )
    assert PROJECT_STATE_STATUSES["failed"] == (
        ProjectStatus.FAILED,
        ProjectStatus.CANCELLED,
    )
