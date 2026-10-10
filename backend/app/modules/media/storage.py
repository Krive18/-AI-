from pathlib import Path

from app.modules.project.storage import LocalPrivateStorage


class LocalObjectStorage(LocalPrivateStorage):
    """Compatibility façade for worker media code over local private storage."""

    def resolve_private_path(self, object_key: str) -> Path:
        return self.download_path(object_key)

    def put_bytes(self, object_key: str, value: bytes) -> Path:
        path = self._path(object_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
        return path

    def put_file(self, object_key: str, source: Path) -> Path:
        return self.put_bytes(object_key, source.read_bytes())
