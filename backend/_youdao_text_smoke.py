"""Real smoke test: run YoudaoSimultaneousRuntime.interpret_text end to end.

Loads the enabled youdao_si provider from the local database, builds the
runtime through the production factory, and interprets a real source.wav
from private storage with ttsRequired=false (text-only mode).
"""

import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app.core.config import Settings
from app.core.database import DatabaseManager
from app.modules.provider.crypto import ProviderSecretCipher
from app.modules.provider.model import (
    ProviderCapability,
    ProviderConfig,
    ProviderVersion,
)
from app.modules.provider_runtime.runtime import ProviderRuntimeFactory

BACKEND_DIR = Path(__file__).resolve().parent
SOURCE_WAV = (
    BACKEND_DIR
    / ".ai_translation_private"
    / "projects"
    / "01M1JDBTWP8ZKKD4B0E41SEXMK"
    / "shared"
    / "source.wav"
)


async def main() -> None:
    settings = Settings(_env_file=BACKEND_DIR / ".env")
    db = DatabaseManager(settings)
    cipher = ProviderSecretCipher(
        settings.provider_secret_encryption_key.get_secret_value()
    )
    async with db.session_factory() as session:
        row = (
            await session.execute(
                select(ProviderConfig, ProviderVersion)
                .join(
                    ProviderVersion,
                    ProviderVersion.id == ProviderConfig.active_version_id,
                )
                .where(
                    ProviderConfig.provider_code == "youdao_si",
                    ProviderConfig.capability
                    == int(ProviderCapability.SIMULTANEOUS_INTERPRETATION),
                )
            )
        ).one_or_none()
        if row is None:
            raise RuntimeError("no enabled youdao_si provider in local database")
        config, version = row
        print(
            f"provider id={config.id} status={config.status} "
            f"endpoint={version.endpoint_url} timeout={version.timeout_ms}ms "
            f"options={sorted((version.config_json or {}).keys())}"
        )
        assert version.endpoint_url.endswith("/stream-si")
        wav = SOURCE_WAV
        if not wav.exists():
            candidates = sorted(
                (BACKEND_DIR / ".ai_translation_private" / "projects").glob(
                    "*/shared/source.wav"
                )
            )
            wav = candidates[0]
        print(f"audio: {wav} ({wav.stat().st_size} bytes)")

        factory = ProviderRuntimeFactory(cipher)
        runtime = factory.build(config, version)
        result = await asyncio.to_thread(runtime.interpret_text, str(wav), "vi-VN")

        print(f"\n=== {len(result.segments)} segments ===")
        for item in result.segments:
            print(
                f"#{item.sequence_no} [{item.start_ms}-{item.end_ms}ms] "
                f"audio={len(item.audio)}B fmt={item.audio_format!r}\n"
                f"  原文: {item.source_text}\n"
                f"  译文: {item.translated_text}"
            )
        print(f"\nusage: audio_seconds={result.usage.audio_seconds}")


if __name__ == "__main__":
    asyncio.run(main())
