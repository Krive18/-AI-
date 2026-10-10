import asyncio
import threading
from base64 import urlsafe_b64encode
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.provider.crypto import ProviderSecretCipher
from app.modules.provider.repository import ProviderRepository
from app.modules.provider.service import (
    ProviderHealthChecker,
    ProviderService,
    _validate_runtime_config,
)
from app.modules.provider_runtime.contracts import ProviderRequestError


def test_runtime_config_rejects_development_provider_codes() -> None:
    with pytest.raises(AppError) as caught:
        _validate_runtime_config(
            "mock_asr",
            1,
            "https://provider.example/asr",
            None,
        )

    assert caught.value.code == "PROVIDER_TYPE_INVALID"


def test_doubao_runtime_config_requires_real_connection_fields() -> None:
    with pytest.raises(AppError) as caught:
        _validate_runtime_config(
            "doubao_asr",
            1,
            "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit",
            {"resource_id": "volc.seedasr.auc"},
        )

    assert caught.value.code == "PROVIDER_CONFIG_INVALID"


def test_doubao_runtime_config_accepts_new_console_api_key_options() -> None:
    _validate_runtime_config(
        "doubao_asr",
        1,
        "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit",
        {
            "query_url": "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query",
            "resource_id": "volc.seedasr.auc",
        },
    )


def test_minimax_runtime_config_requires_voice_and_job_endpoints() -> None:
    with pytest.raises(AppError) as caught:
        _validate_runtime_config(
            "minimax",
            3,
            "https://api.minimax.chat/v1/t2a_async_v2",
            {
                "poll_url": "https://api.minimax.chat/v1/query/t2a_async_query_v2",
                "download_url": "https://api.minimax.chat/v1/files/retrieve_content",
            },
        )

    assert caught.value.code == "PROVIDER_CONFIG_INVALID"


def test_youdao_runtime_config_accepts_only_the_official_websocket_endpoint() -> None:
    _validate_runtime_config(
        "youdao_si",
        4,
        "wss://openapi.youdao.com/stream-audio/stream-si",
        {"app_key": "application-id", "tts_sex": "female"},
    )

    with pytest.raises(AppError) as caught:
        _validate_runtime_config(
            "youdao_si",
            4,
            "wss://attacker.example/stream-audio/stream-si",
            {"app_key": "application-id", "tts_sex": "female"},
        )

    assert caught.value.code == "PROVIDER_ENDPOINT_INVALID"


class _FailingHealthChecker:
    def check(self, _config: object, _version: object) -> str:
        raise ProviderRequestError("PROVIDER_AUTH_FAILED", "供应商认证失败")


class _ProviderRepositoryStub:
    async def get_config(self, _public_id: str, *, for_update: bool = False) -> object:
        return SimpleNamespace(
            id=1,
            public_id="01M1GTESTPROVIDER0000000000",
            provider_code="doubao_asr",
            active_version_id=7,
        )


class _SessionStub:
    def __init__(self) -> None:
        self.rolled_back = False
        self.committed = False
        self.added: list[object] = []

    async def get(self, _model: object, _identifier: int) -> object:
        return SimpleNamespace(id=7)

    async def rollback(self) -> None:
        self.rolled_back = True

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True


@pytest.mark.asyncio
async def test_provider_connection_failure_returns_a_safe_gateway_error() -> None:
    session = _SessionStub()
    service = ProviderService(
        cast(ProviderRepository, _ProviderRepositoryStub()),
        cast(AsyncSession, session),
        ProviderSecretCipher(urlsafe_b64encode(b"a" * 32).decode()),
        "request-id",
        checker=cast(ProviderHealthChecker, _FailingHealthChecker()),
    )

    with pytest.raises(AppError) as caught:
        await service.test(actor_id=1, public_id="01M1GTESTPROVIDER0000000000")

    assert caught.value.code == "PROVIDER_AUTH_FAILED"
    assert caught.value.message == "供应商认证失败"
    assert caught.value.status_code == 502
    assert session.rolled_back is True


class _BlockingHealthChecker:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def check(self, _config: object, _version: object) -> str:
        self.started.set()
        if not self.release.wait(0.5):
            raise ProviderRequestError("PROVIDER_TIMEOUT", "检查阻塞了事件循环")
        return "CONNECTED"


@pytest.mark.asyncio
async def test_provider_connection_check_does_not_block_the_event_loop() -> None:
    session = _SessionStub()
    checker = _BlockingHealthChecker()
    service = ProviderService(
        cast(ProviderRepository, _ProviderRepositoryStub()),
        cast(AsyncSession, session),
        ProviderSecretCipher(urlsafe_b64encode(b"a" * 32).decode()),
        "request-id",
        checker=cast(ProviderHealthChecker, checker),
    )

    checking = asyncio.create_task(
        service.test(actor_id=1, public_id="01M1GTESTPROVIDER0000000000")
    )
    for _ in range(50):
        if checker.started.is_set():
            break
        await asyncio.sleep(0.002)
    checker.release.set()

    assert await checking == "CONNECTED"
    assert session.committed is True
