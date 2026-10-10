from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.modules.cost.model import ProviderPrice
from app.modules.provider.model import ProviderConfig, ProviderStatus, ProviderVersion


def _now() -> datetime:
    value = datetime.now(UTC).replace(tzinfo=None)
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


class ProviderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_configs(self) -> list[ProviderConfig]:
        result = await self.session.execute(
            select(ProviderConfig).order_by(
                ProviderConfig.capability, ProviderConfig.priority, ProviderConfig.id
            )
        )
        return list(result.scalars())

    async def get_config(
        self, public_id: str, *, for_update: bool = False
    ) -> ProviderConfig | None:
        statement = select(ProviderConfig).where(ProviderConfig.public_id == public_id)
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def get_version(self, public_id: str) -> ProviderVersion | None:
        return (
            await self.session.execute(
                select(ProviderVersion).where(ProviderVersion.public_id == public_id)
            )
        ).scalar_one_or_none()

    async def list_versions(
        self, config_id: int, cursor: int | None, limit: int
    ) -> list[ProviderVersion]:
        statement = (
            select(ProviderVersion)
            .where(ProviderVersion.provider_config_id == config_id)
            .order_by(ProviderVersion.id.desc())
            .limit(limit + 1)
        )
        if cursor is not None:
            statement = statement.where(ProviderVersion.id < cursor)
        return [value for value in (await self.session.execute(statement)).scalars()]

    async def list_prices(
        self,
        provider_version_id: int | None,
        capability: int | None,
        locale: str | None,
    ) -> list[ProviderPrice]:
        statement = select(ProviderPrice).order_by(
            ProviderPrice.effective_from.desc(), ProviderPrice.id.desc()
        )
        if provider_version_id is not None:
            statement = statement.where(
                ProviderPrice.provider_version_id == provider_version_id
            )
        if capability is not None:
            statement = statement.where(ProviderPrice.capability == capability)
        if locale is not None:
            statement = statement.where(ProviderPrice.target_locale == locale)
        return [value for value in (await self.session.execute(statement)).scalars()]

    async def create(
        self,
        *,
        provider_code: str,
        display_name: str,
        capability: int,
        priority: int,
        locales: list[str] | None,
        model_name: str,
        endpoint_url: str,
        timeout_ms: int,
        config: dict[str, object] | None,
        encrypted_secret: bytes,
        created_by: int,
    ) -> ProviderConfig:
        now = _now()
        config_row = ProviderConfig(
            public_id=str(ULID()),
            provider_code=provider_code,
            display_name=display_name,
            capability=capability,
            status=int(ProviderStatus.ENABLED),
            priority=priority,
            supported_locales_json=locales,
            active_version_id=None,
            created_at=now,
            updated_at=now,
        )
        self.session.add(config_row)
        await self.session.flush()
        version = ProviderVersion(
            public_id=str(ULID()),
            provider_config_id=config_row.id,
            version_no=1,
            model_name=model_name,
            endpoint_url=endpoint_url,
            timeout_ms=timeout_ms,
            config_json=config,
            encrypted_secret=encrypted_secret,
            encryption_key_id="local-v1",
            status=int(ProviderStatus.ENABLED),
            created_by=created_by,
            created_at=now,
        )
        self.session.add(version)
        await self.session.flush()
        config_row.active_version_id = version.id
        return config_row

    async def create_version(
        self,
        config: ProviderConfig,
        *,
        model_name: str,
        endpoint_url: str,
        timeout_ms: int,
        options: dict[str, object] | None,
        encrypted_secret: bytes,
        created_by: int,
    ) -> ProviderVersion:
        next_number = (
            int(
                (
                    await self.session.scalar(
                        select(
                            func.coalesce(func.max(ProviderVersion.version_no), 0)
                        ).where(ProviderVersion.provider_config_id == config.id)
                    )
                )
                or 0
            )
            + 1
        )
        version = ProviderVersion(
            public_id=str(ULID()),
            provider_config_id=config.id,
            version_no=next_number,
            model_name=model_name,
            endpoint_url=endpoint_url,
            timeout_ms=timeout_ms,
            config_json=options,
            encrypted_secret=encrypted_secret,
            encryption_key_id="local-v1",
            status=int(ProviderStatus.ENABLED),
            created_by=created_by,
            created_at=_now(),
        )
        self.session.add(version)
        await self.session.flush()
        return version

    async def active_capability_count_for_update(self, capability: int) -> int:
        result = await self.session.execute(
            select(ProviderConfig.id)
            .where(
                ProviderConfig.capability == capability,
                ProviderConfig.status == int(ProviderStatus.ENABLED),
            )
            .with_for_update()
        )
        return len(result.scalars().all())

    async def save_config(
        self,
        config: ProviderConfig,
        expected_updated_at: datetime,
        *,
        display_name: str,
        status: int,
        priority: int,
        locales: list[str] | None,
        active_version_id: int | None,
    ) -> bool:
        with self.session.no_autoflush:
            result = await self.session.execute(
                update(ProviderConfig)
                .where(
                    ProviderConfig.id == config.id,
                    ProviderConfig.updated_at == expected_updated_at,
                )
                .values(
                    display_name=display_name,
                    status=status,
                    priority=priority,
                    supported_locales_json=locales,
                    active_version_id=active_version_id,
                    updated_at=_now(),
                )
            )
        return bool(getattr(result, "rowcount", 0))

    async def create_price(
        self,
        *,
        provider_version_id: int,
        capability: int,
        model_name: str,
        locale: str | None,
        billing_unit: str,
        unit_size: int,
        unit_price: int,
        currency: str,
        effective_from: datetime,
        effective_to: datetime | None,
        created_by: int,
    ) -> ProviderPrice:
        price = ProviderPrice(
            public_id=str(ULID()),
            provider_version_id=provider_version_id,
            capability=capability,
            model_name=model_name,
            target_locale=locale,
            billing_unit=billing_unit,
            unit_size=unit_size,
            unit_price_microunit=unit_price,
            currency=currency,
            effective_from=effective_from,
            effective_to=effective_to,
            created_by=created_by,
            created_at=_now(),
        )
        self.session.add(price)
        await self.session.flush()
        return price
