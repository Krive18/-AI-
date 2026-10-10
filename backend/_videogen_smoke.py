"""Real smoke test: SeedanceVideoRuntime against the live Ark video API.

Reuses the local database's Ark API key (from any enabled ark-family provider)
to create a 480p/5s image-to-video task through the production runtime, then
polls until completion and saves the MP4 next to this script. If the Seedance
2.0 models are not enabled on the account, the provider's error response is
printed verbatim for diagnosis.
"""

import asyncio
import base64
import time
from pathlib import Path

from sqlalchemy import select

from app.core.config import Settings
from app.core.database import DatabaseManager
from app.modules.provider.crypto import ProviderSecretCipher
from app.modules.provider.model import (
    ProviderConfig,
    ProviderStatus,
    ProviderVersion,
)
from app.modules.provider_runtime.contracts import ProviderRequestError
from app.modules.provider_runtime.runtime import (
    ProviderRuntimeFactory,
    SeedanceVideoRuntime,
)

BACKEND_DIR = Path(__file__).resolve().parent
OUTPUT_MP4 = BACKEND_DIR / "_videogen_smoke.mp4"
TINY_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
MODELS = {
    "standard": "doubao-seedance-2-0-260128",
    "fast": "doubao-seedance-2-0-fast-260128",
    "mini": "doubao-seedance-2-0-mini-260615",
}


def _reference_data_uri() -> str:
    candidates = sorted(
        (BACKEND_DIR / ".ai_translation_private" / "imagegen").glob("*/0.png")
    )
    if candidates:
        payload = candidates[0].read_bytes()
        print(f"reference: {candidates[0]} ({len(payload)} bytes)")
    else:
        payload = base64.b64decode(TINY_PNG)
        print("reference: embedded 1x1 png")
    return f"data:image/png;base64,{base64.b64encode(payload).decode('ascii')}"


async def main() -> None:
    settings = Settings(_env_file=BACKEND_DIR / ".env")
    db = DatabaseManager(settings)
    cipher = ProviderSecretCipher(
        settings.provider_secret_encryption_key.get_secret_value()
    )
    async with db.session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(ProviderConfig, ProviderVersion).join(
                        ProviderVersion,
                        ProviderVersion.id == ProviderConfig.active_version_id,
                    )
                )
            )
            .all()
        )
    key_row = next(
        (row for row in rows if row[0].provider_code in {"seedance_video", "ark"}),
        None,
    )
    if key_row is None:
        raise RuntimeError("no ark-family provider in local database")
    config, version = key_row
    print(
        f"key source: provider={config.provider_code} endpoint={version.endpoint_url}"
    )

    if config.provider_code == "seedance_video":
        runtime = ProviderRuntimeFactory(cipher).build(config, version)
    else:
        # Reuse the Ark key with a synthetic video provider version.
        synthetic = ProviderVersion(
            model_name="video-generation",
            endpoint_url=(
                "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"
            ),
            timeout_ms=30000,
            config_json={"models": dict(MODELS)},
            encrypted_secret=version.encrypted_secret,
            status=int(ProviderStatus.ENABLED),
        )
        credential = cipher.decrypt(version.encrypted_secret)
        runtime = SeedanceVideoRuntime(
            synthetic, credential, ProviderRuntimeFactory(cipher)._transport
        )

    started = time.monotonic()
    try:
        result = await asyncio.to_thread(
            runtime.generate_video,
            "镜头缓慢推进，画面轻微呼吸感，保持主体稳定",
            _reference_data_uri(),
            "480p",
            5,
            3,
        )
    except ProviderRequestError as error:
        elapsed = round(time.monotonic() - started, 1)
        print(f"\n=== provider rejected ({elapsed}s) ===")
        print(f"code={error.code}")
        print(f"message={error.message}")
        return
    elapsed = round(time.monotonic() - started, 1)
    OUTPUT_MP4.write_bytes(result.video)
    print(f"\n=== succeeded in {elapsed}s ===")
    print(f"saved {len(result.video)} bytes -> {OUTPUT_MP4}")
    print(f"content_type={result.content_type} output_units={result.usage.output_units}")


if __name__ == "__main__":
    asyncio.run(main())
