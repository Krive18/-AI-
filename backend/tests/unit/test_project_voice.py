from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.errors import AppError
from app.modules.project.service import ProjectService
from app.modules.project.storage import LocalPrivateStorage


def _service(tmp_path: Path) -> ProjectService:
    return ProjectService(
        session=None,  # type: ignore[arg-type]
        storage=LocalPrivateStorage(tmp_path),
    )


async def test_create_rejects_blank_voice_id(tmp_path: Path) -> None:
    service = _service(tmp_path)
    account = SimpleNamespace(id=1)

    with pytest.raises(AppError, match="VOICE_INVALID"):
        await service.create_project(
            account,  # type: ignore[arg-type]
            "idem-key-1",
            "upload-token",
            "name",
            ["en-US"],
            voice_id="   ",
        )


async def test_create_rejects_overlong_voice_id(tmp_path: Path) -> None:
    service = _service(tmp_path)
    account = SimpleNamespace(id=1)

    with pytest.raises(AppError, match="VOICE_INVALID"):
        await service.create_project(
            account,  # type: ignore[arg-type]
            "idem-key-1",
            "upload-token",
            "name",
            ["en-US"],
            voice_id="x" * 65,
        )
