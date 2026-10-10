from redis.asyncio import Redis

from app.core.config import Settings


class RedisManager:
    def __init__(self, settings: Settings) -> None:
        self._requires_production_version = settings.app_env == "production"
        self._production_version_verified = False
        self.client: Redis = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            protocol=settings.redis_protocol,
        )

    async def ping(self) -> None:
        await self.client.ping()
        if self._requires_production_version and not self._production_version_verified:
            server_info = await self.client.info(section="server")
            raw_version = str(server_info.get("redis_version", ""))
            try:
                version = tuple(int(part) for part in raw_version.split(".")[:2])
            except ValueError as error:
                raise RuntimeError(
                    "Redis server did not report a valid version"
                ) from error
            if len(version) != 2 or version < (7, 2):
                raise RuntimeError("Production requires Redis 7.2 or newer")
            self._production_version_verified = True

    async def close(self) -> None:
        await self.client.aclose()
