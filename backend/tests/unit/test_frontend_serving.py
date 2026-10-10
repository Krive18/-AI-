from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app


class _StubManager:
    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        return None


def _settings(dist: Path | None) -> Settings:
    return Settings(
        app_env="test",
        database_url="mysql+asyncmy://unused:unused@127.0.0.1/unused",
        redis_url="redis://127.0.0.1:6379/15",
        session_hash_key="spa-test-session-key-that-is-at-least-32-bytes",
        provider_secret_encryption_key="c3BhLXRlc3QtcHJvdmlkZXIta2V5LTMyLWJ5dGVzLSE=",
        frontend_dist=dist,
    )


def _make_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa</html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    return dist


@pytest.mark.asyncio
async def test_spa_serves_index_and_assets(tmp_path: Path) -> None:
    dist = _make_dist(tmp_path)
    app = create_app(
        _settings(dist),
        database_manager=_StubManager(),
        redis_manager=_StubManager(),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        root = await client.get("/")
        assert root.status_code == 200
        assert root.text == "<html>spa</html>"

        deep_link = await client.get("/translations/01M1ABC")
        assert deep_link.status_code == 200
        assert deep_link.text == "<html>spa</html>"

        asset = await client.get("/assets/app.js")
        assert asset.status_code == 200
        assert asset.text == "console.log(1)"


@pytest.mark.asyncio
async def test_spa_fallback_does_not_swallow_unknown_api_paths(
    tmp_path: Path,
) -> None:
    dist = _make_dist(tmp_path)
    app = create_app(
        _settings(dist),
        database_manager=_StubManager(),
        redis_manager=_StubManager(),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        response = await client.get("/api/v1/definitely-not-a-route")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_spa_not_mounted_without_dist(tmp_path: Path) -> None:
    app = create_app(
        _settings(tmp_path / "missing"),
        database_manager=_StubManager(),
        redis_manager=_StubManager(),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        response = await client.get("/")

    assert response.status_code == 404
