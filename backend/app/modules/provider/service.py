from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from urllib.parse import urlparse

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.audit.model import AuditLog
from app.modules.cost.model import ProviderPrice
from app.modules.provider.crypto import ProviderSecretCipher
from app.modules.provider.model import (
    ProviderCapability,
    ProviderConfig,
    ProviderStatus,
    ProviderVersion,
)
from app.modules.provider.repository import ProviderRepository, _now
from app.modules.provider_runtime.contracts import ProviderRequestError
from app.modules.provider_runtime.runtime import ProviderRuntimeFactory

_PROVIDER_CAPABILITIES = {
    "doubao_asr": 1,
    "ark": 2,
    "minimax": 3,
    "youdao_si": 4,
    "seedream": 5,
    "ark_vision": 6,
    "seedance_video": 7,
}
_URL_OPTION_KEYS = {"query_url", "poll_url", "download_url"}
_REQUIRED_OPTIONS = {
    "doubao_asr": {"query_url", "resource_id"},
    "minimax": {"poll_url", "download_url", "default_voice_id"},
    "youdao_si": {"app_key", "tts_sex"},
}
_YOUDAO_ENDPOINT = "wss://openapi.youdao.com/stream-audio/stream-si"


def _validate_https_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username:
        raise AppError(
            "PROVIDER_ENDPOINT_INVALID",
            "供应商接口必须是无内嵌凭据的 HTTPS 地址",
            status_code=422,
        )


def _validate_runtime_config(
    provider_code: str,
    capability: int,
    endpoint_url: str,
    options: dict[str, object] | None,
) -> None:
    code = provider_code.casefold()
    expected_capability = _PROVIDER_CAPABILITIES.get(code, -1)
    if expected_capability == -1 or (
        expected_capability is not None and expected_capability != capability
    ):
        raise AppError(
            "PROVIDER_TYPE_INVALID",
            "供应商代码与能力不匹配",
            status_code=422,
        )
    if code == "youdao_si":
        if endpoint_url != _YOUDAO_ENDPOINT:
            raise AppError(
                "PROVIDER_ENDPOINT_INVALID",
                "智能翻译服务必须使用官方 WSS 接口地址",
                status_code=422,
            )
    else:
        _validate_https_url(endpoint_url)
    missing = [
        key
        for key in _REQUIRED_OPTIONS.get(code, set())
        if not isinstance((options or {}).get(key), str)
        or not str((options or {}).get(key)).strip()
    ]
    if missing:
        raise AppError(
            "PROVIDER_CONFIG_INVALID",
            "供应商扩展配置不完整",
            status_code=422,
        )
    if code == "youdao_si" and (options or {}).get("tts_sex") not in {
        "female",
        "male",
    }:
        raise AppError(
            "PROVIDER_CONFIG_INVALID", "智能翻译服务音色配置无效", status_code=422
        )
    if code == "seedance_video":
        models = (options or {}).get("models")
        tier_models = (
            [models.get(key) for key in ("standard", "fast", "mini")]
            if isinstance(models, dict)
            else []
        )
        if len(tier_models) != 3 or any(
            not isinstance(model, str) or not model.strip() for model in tier_models
        ):
            raise AppError(
                "PROVIDER_CONFIG_INVALID",
                "视频生成服务扩展配置不完整（需要标准版、快速版、轻量版三个模型 ID）",
                status_code=422,
            )
    for key in _URL_OPTION_KEYS:
        value = (options or {}).get(key)
        if value is not None:
            if not isinstance(value, str):
                raise AppError(
                    "PROVIDER_CONFIG_INVALID",
                    "供应商扩展配置无效",
                    status_code=422,
                )
            _validate_https_url(value)


class ProviderHealthChecker(Protocol):
    def check(self, config: ProviderConfig, version: ProviderVersion) -> str: ...


class RuntimeHealthChecker:
    def __init__(self, factory: ProviderRuntimeFactory) -> None:
        self._factory = factory

    def check(self, config: ProviderConfig, version: ProviderVersion) -> str:
        try:
            self._factory.build(config, version).probe()
        except ProviderRequestError as error:
            # A silent authenticated probe proves the Doubao key and resource access.
            if (
                config.provider_code not in {"doubao_asr", "youdao_si"}
                or error.code != "PROVIDER_NO_SPEECH"
            ):
                raise
        return "CONNECTED"


@dataclass(frozen=True, slots=True)
class ProviderMutation:
    config: ProviderConfig
    version: ProviderVersion | None = None


class ProviderService:
    def __init__(
        self,
        repository: ProviderRepository,
        session: AsyncSession,
        cipher: ProviderSecretCipher,
        request_id: str,
        checker: ProviderHealthChecker | None = None,
    ) -> None:
        self._repo, self._session, self._cipher, self._request_id = (
            repository,
            session,
            cipher,
            request_id,
        )
        self._checker = checker or RuntimeHealthChecker(ProviderRuntimeFactory(cipher))

    async def create(
        self,
        *,
        actor_id: int,
        provider_code: str,
        display_name: str,
        capability: int,
        priority: int,
        locales: list[str] | None,
        model_name: str,
        endpoint_url: str,
        timeout_ms: int,
        options: dict[str, object] | None,
        api_key: str,
    ) -> ProviderConfig:
        _validate_runtime_config(provider_code, capability, endpoint_url, options)
        try:
            config = await self._repo.create(
                provider_code=provider_code,
                display_name=display_name,
                capability=capability,
                priority=priority,
                locales=locales,
                model_name=model_name,
                endpoint_url=endpoint_url,
                timeout_ms=timeout_ms,
                config=options,
                encrypted_secret=self._cipher.encrypt(api_key),
                created_by=actor_id,
            )
            await self._audit(
                "PROVIDER_CREATED",
                actor_id,
                config,
                {"providerCode": config.provider_code, "capability": config.capability},
            )
            await self._session.commit()
            return config
        except SQLAlchemyError:
            await self._session.rollback()
            raise AppError(
                "PROVIDER_UNAVAILABLE", "供应商配置服务暂时不可用", status_code=503
            ) from None

    async def update(
        self,
        *,
        actor_id: int,
        public_id: str,
        expected_updated_at: datetime,
        display_name: str | None,
        priority: int | None,
        status: ProviderStatus | None,
        locales: list[str] | None,
        model_name: str | None,
        endpoint_url: str | None,
        timeout_ms: int | None,
        options: dict[str, object] | None,
        api_key: str | None,
    ) -> ProviderMutation:
        try:
            config = await self._require_config(public_id)
            active = await self._active_version(config)
            _validate_runtime_config(
                config.provider_code,
                config.capability,
                endpoint_url or active.endpoint_url,
                options if options is not None else active.config_json,
            )
            if (
                status is ProviderStatus.DISABLED
                and config.status == int(ProviderStatus.ENABLED)
                and config.capability
                in {
                    int(ProviderCapability.ASR),
                    int(ProviderCapability.TRANSLATION),
                    int(ProviderCapability.TTS),
                }
                and await self._repo.active_capability_count_for_update(
                    config.capability
                )
                <= 1
            ):
                raise AppError(
                    "LAST_PROVIDER_REQUIRED",
                    "每项关键能力至少保留一个启用供应商",
                    status_code=409,
                )
            if config.updated_at != expected_updated_at.replace(tzinfo=None):
                raise AppError(
                    "PROVIDER_VERSION_CONFLICT",
                    "供应商配置已更新，请刷新后重试",
                    status_code=409,
                )
            next_name = config.display_name if display_name is None else display_name
            next_priority = config.priority if priority is None else priority
            next_status = config.status if status is None else int(status)
            next_locales = config.supported_locales_json if locales is None else locales
            version: ProviderVersion | None = None
            if any(
                value is not None
                for value in (model_name, endpoint_url, timeout_ms, options, api_key)
            ):
                previous = active
                version = await self._repo.create_version(
                    config,
                    model_name=model_name or previous.model_name,
                    endpoint_url=endpoint_url or previous.endpoint_url,
                    timeout_ms=timeout_ms or previous.timeout_ms,
                    options=options if options is not None else previous.config_json,
                    encrypted_secret=self._cipher.encrypt(api_key)
                    if api_key is not None
                    else previous.encrypted_secret,
                    created_by=actor_id,
                )
            if not await self._repo.save_config(
                config,
                expected_updated_at.replace(tzinfo=None),
                display_name=next_name,
                status=next_status,
                priority=next_priority,
                locales=next_locales,
                active_version_id=version.id if version else config.active_version_id,
            ):
                raise AppError(
                    "PROVIDER_VERSION_CONFLICT",
                    "供应商配置已更新，请刷新后重试",
                    status_code=409,
                )
            await self._session.refresh(config)
            await self._audit(
                "PROVIDER_UPDATED",
                actor_id,
                config,
                {
                    "newVersion": version.public_id if version else None,
                    "status": config.status,
                    "priority": config.priority,
                },
            )
            await self._session.commit()
            return ProviderMutation(config, version)
        except AppError:
            await self._session.rollback()
            raise
        except SQLAlchemyError:
            await self._session.rollback()
            raise AppError(
                "PROVIDER_UNAVAILABLE", "供应商配置服务暂时不可用", status_code=503
            ) from None

    async def activate(
        self,
        *,
        actor_id: int,
        public_id: str,
        version_public_id: str,
        expected_updated_at: datetime,
    ) -> ProviderConfig:
        try:
            config = await self._require_config(public_id)
            version = await self._repo.get_version(version_public_id)
            if version is None or version.provider_config_id != config.id:
                raise AppError(
                    "PROVIDER_VERSION_NOT_FOUND", "供应商版本不存在", status_code=404
                )
            if config.updated_at != expected_updated_at.replace(
                tzinfo=None
            ) or not await self._repo.save_config(
                config,
                expected_updated_at.replace(tzinfo=None),
                display_name=config.display_name,
                status=config.status,
                priority=config.priority,
                locales=config.supported_locales_json,
                active_version_id=version.id,
            ):
                raise AppError(
                    "PROVIDER_VERSION_CONFLICT",
                    "供应商配置已更新，请刷新后重试",
                    status_code=409,
                )
            await self._session.refresh(config)
            await self._audit(
                "PROVIDER_VERSION_ACTIVATED",
                actor_id,
                config,
                {"versionId": version.public_id},
            )
            await self._session.commit()
            return config
        except AppError:
            await self._session.rollback()
            raise
        except SQLAlchemyError:
            await self._session.rollback()
            raise AppError(
                "PROVIDER_UNAVAILABLE", "供应商配置服务暂时不可用", status_code=503
            ) from None

    async def create_price(
        self,
        *,
        actor_id: int,
        version_public_id: str,
        capability: int,
        locale: str | None,
        billing_unit: str,
        unit_size: int,
        unit_price: int,
        currency: str,
        effective_from: datetime,
        effective_to: datetime | None,
    ) -> ProviderPrice:
        version = await self._repo.get_version(version_public_id)
        if version is None:
            raise AppError(
                "PROVIDER_VERSION_NOT_FOUND", "供应商版本不存在", status_code=404
            )
        config = await self._session.get(ProviderConfig, version.provider_config_id)
        if (
            config is None
            or config.capability != capability
            or billing_unit not in {"characters", "tokens", "milliseconds", "seconds"}
            or (effective_to is not None and effective_to <= effective_from)
        ):
            raise AppError(
                "PROVIDER_PRICE_INVALID", "供应商价格规则无效", status_code=422
            )
        try:
            price = await self._repo.create_price(
                provider_version_id=version.id,
                capability=capability,
                model_name=version.model_name,
                locale=locale,
                billing_unit=billing_unit,
                unit_size=unit_size,
                unit_price=unit_price,
                currency=currency,
                effective_from=effective_from,
                effective_to=effective_to,
                created_by=actor_id,
            )
            await self._audit(
                "PROVIDER_PRICE_CREATED",
                actor_id,
                config,
                {"priceId": price.public_id, "versionId": version.public_id},
            )
            await self._session.commit()
            return price
        except SQLAlchemyError:
            await self._session.rollback()
            raise AppError(
                "PROVIDER_UNAVAILABLE", "供应商配置服务暂时不可用", status_code=503
            ) from None

    async def test(self, *, actor_id: int, public_id: str) -> str:
        try:
            config = await self._require_config(public_id)
            version = await self._active_version(config)
            state = await asyncio.to_thread(self._checker.check, config, version)
            await self._audit("PROVIDER_TESTED", actor_id, config, {"result": state})
            await self._session.commit()
            return state
        except AppError:
            await self._session.rollback()
            raise
        except ProviderRequestError as error:
            await self._session.rollback()
            raise AppError(error.code, error.message, status_code=502) from None
        except SQLAlchemyError:
            await self._session.rollback()
            raise AppError(
                "PROVIDER_UNAVAILABLE", "供应商配置服务暂时不可用", status_code=503
            ) from None

    async def _require_config(self, public_id: str) -> ProviderConfig:
        config = await self._repo.get_config(public_id, for_update=True)
        if config is None:
            raise AppError("PROVIDER_NOT_FOUND", "供应商不存在", status_code=404)
        return config

    async def _active_version(self, config: ProviderConfig) -> ProviderVersion:
        version = (
            (await self._session.get(ProviderVersion, config.active_version_id))
            if config.active_version_id
            else None
        )
        if version is None:
            raise AppError(
                "PROVIDER_VERSION_NOT_FOUND", "供应商没有可用版本", status_code=409
            )
        return version

    async def _audit(
        self,
        action: str,
        actor_id: int,
        config: ProviderConfig,
        after: dict[str, object],
    ) -> None:
        self._session.add(
            AuditLog(
                actor_id=actor_id,
                action=action,
                resource_type="provider",
                resource_public_id=config.public_id,
                request_id=self._request_id,
                ip_address=None,
                before_data=None,
                after_data=after,
                created_at=_now(),
            )
        )
        await self._session.flush()
