from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from pathlib import Path

from app.modules.project.schemas import UPLOAD_SESSION_SECONDS, UploadSession


class LocalPrivateStorage:
    """Development-only private file storage rooted outside public static files."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def create_upload(
        self, account_id: int, filename: str, content_type: str, total_bytes: int
    ) -> UploadSession:
        token = secrets.token_urlsafe(32)
        object_key = f"uploads/{account_id}/{token}/source"
        session = UploadSession(
            token, account_id, filename, content_type, total_bytes, object_key
        )
        self._write_json(
            f"sessions/{token}.json",
            {
                "accountId": account_id,
                "filename": filename,
                "contentType": content_type,
                "totalBytes": total_bytes,
                "objectKey": object_key,
                "expiresAt": int(time.time()) + UPLOAD_SESSION_SECONDS,
            },
        )
        return session

    def append_chunk(
        self, token: str, account_id: int, offset: int, content: bytes
    ) -> int:
        session = self.get_upload(token, account_id)
        destination = self._path(session.object_key + ".part")
        destination.parent.mkdir(parents=True, exist_ok=True)
        current = destination.stat().st_size if destination.exists() else 0
        if offset != current or current + len(content) > session.total_bytes:
            raise ValueError("invalid upload chunk offset or size")
        with destination.open("ab") as stream:
            stream.write(content)
        return current + len(content)

    def complete_upload(self, token: str, account_id: int) -> UploadSession:
        session = self.get_upload(token, account_id)
        part = self._path(session.object_key + ".part")
        if not part.exists() or part.stat().st_size != session.total_bytes:
            raise ValueError("upload is incomplete")
        final = self._path(session.object_key)
        final.parent.mkdir(parents=True, exist_ok=True)
        os.replace(part, final)
        self._write_json(
            f"sessions/{token}.json",
            {
                "accountId": account_id,
                "filename": session.filename,
                "contentType": session.content_type,
                "totalBytes": session.total_bytes,
                "objectKey": session.object_key,
                "completed": True,
                "expiresAt": int(time.time()) + UPLOAD_SESSION_SECONDS,
            },
        )
        return session

    def get_upload(self, token: str, account_id: int) -> UploadSession:
        payload = self._read_json(f"sessions/{token}.json")
        if (
            payload is None
            or payload["accountId"] != account_id
            or int(str(payload.get("expiresAt", 0))) < int(time.time())
        ):
            raise ValueError("upload session not found")
        return UploadSession(
            token,
            account_id,
            str(payload["filename"]),
            str(payload["contentType"]),
            int(str(payload["totalBytes"])),
            str(payload["objectKey"]),
        )

    def object_size_and_hash(self, object_key: str) -> tuple[int, str]:
        path = self._path(object_key)
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return path.stat().st_size, digest.hexdigest()

    def download_path(self, object_key: str) -> Path:
        path = self._path(object_key)
        if not path.is_file():
            raise FileNotFoundError(object_key)
        return path

    def delete(self, object_key: str) -> None:
        try:
            self._path(object_key).unlink()
        except FileNotFoundError:
            pass

    def idempotency_get(self, account_id: int, key: str) -> str | None:
        payload = self._read_json(
            f"idempotency/{account_id}/{hashlib.sha256(key.encode()).hexdigest()}.json"
        )
        return None if payload is None else str(payload["projectId"])

    def idempotency_put(self, account_id: int, key: str, project_id: str) -> None:
        self._write_json(
            f"idempotency/{account_id}/{hashlib.sha256(key.encode()).hexdigest()}.json",
            {"projectId": project_id},
        )

    def _path(self, relative: str) -> Path:
        path = (self._root / relative).resolve()
        if self._root not in path.parents and path != self._root:
            raise ValueError("invalid private storage path")
        return path

    def _write_json(self, relative: str, value: dict[str, object]) -> None:
        path = self._path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value), encoding="utf-8")
        os.replace(temporary, path)

    def _read_json(self, relative: str) -> dict[str, object] | None:
        path = self._path(relative)
        return (
            None if not path.exists() else json.loads(path.read_text(encoding="utf-8"))
        )
