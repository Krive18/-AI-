from __future__ import annotations

import argparse
import asyncio
import logging
import time
from collections.abc import Sequence

from app.core.config import Settings
from app.core.database import DatabaseManager
from app.core.redis import RedisManager
from app.modules.media.storage import LocalObjectStorage
from app.modules.media_runtime.ffmpeg import FFmpeg
from app.modules.provider.crypto import ProviderSecretCipher
from app.modules.provider_runtime.runtime import ProviderRuntimeFactory
from app.workers.cleanup import sweep_private_storage
from app.workers.pipeline import TranslationWorker

_SWEEP_INTERVAL_SECONDS = 3600.0


async def run_worker(settings: Settings, *, once: bool) -> None:
    database = DatabaseManager(settings)
    redis = RedisManager(settings)
    ffmpeg = FFmpeg()
    await asyncio.to_thread(ffmpeg.check_available)
    pipeline = TranslationWorker(
        database.session_factory,
        redis.client,
        LocalObjectStorage(settings.private_storage_root),
        ffmpeg,
        ProviderRuntimeFactory(
            ProviderSecretCipher(
                settings.provider_secret_encryption_key.get_secret_value()
            )
        ),
        lease_seconds=settings.worker_lease_seconds,
        max_concurrency=settings.worker_max_concurrency,
    )
    last_sweep = 0.0
    try:
        while True:
            completed = await pipeline.run_once()
            if once:
                return
            if time.monotonic() - last_sweep >= _SWEEP_INTERVAL_SECONDS:
                last_sweep = time.monotonic()
                try:
                    await sweep_private_storage(
                        settings.private_storage_root, database.session_factory
                    )
                except Exception:
                    logging.getLogger(__name__).exception(
                        "private storage sweep failed"
                    )
            if completed.projects == 0 and completed.tasks == 0:
                await asyncio.sleep(settings.worker_poll_interval_seconds)
    finally:
        await redis.close()
        await database.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.worker")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process the current queue once and exit",
    )
    arguments = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        settings = Settings()  # type: ignore[call-arg]
        asyncio.run(run_worker(settings, once=arguments.once))
    except KeyboardInterrupt:
        return 0
    except Exception:
        logging.getLogger(__name__).exception("worker stopped")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
