import json
import threading
from typing import Self

from pytest import MonkeyPatch

from app.modules.provider_runtime import websocket
from app.modules.provider_runtime.websocket import SyncWebSocketTransport


class _Socket:
    def __init__(self) -> None:
        self.authenticated = threading.Event()
        self.ended = threading.Event()
        self.received = 0
        self.sent: list[bytes] = []
        threading.Timer(0.05, self.authenticated.set).start()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def recv(self, timeout: float) -> str:
        self.received += 1
        if self.received == 1:
            assert self.authenticated.wait(timeout)
            return json.dumps({"action": "started", "errorCode": "0"})
        assert self.ended.wait(timeout)
        return json.dumps({"action": "recognition", "errorCode": "0", "isEnd": True})

    def send(self, payload: bytes) -> None:
        if payload != b'{"end": "true"}':
            assert self.authenticated.is_set(), "audio was sent before authentication"
        else:
            self.ended.set()
        self.sent.append(payload)

    def close(self) -> None:
        self.ended.set()


def test_transport_waits_for_authentication_before_streaming(
    monkeypatch: MonkeyPatch,
) -> None:
    socket = _Socket()
    monkeypatch.setattr(websocket, "connect", lambda *args, **kwargs: socket)

    messages = SyncWebSocketTransport().exchange(
        "wss://openapi.youdao.com/stream-audio/stream-si",
        b"abcd",
        chunk_bytes=2,
        interval_seconds=0,
        timeout_seconds=1,
    )

    assert socket.sent == [b"ab", b"cd", b'{"end": "true"}']
    assert len(messages) == 2
