from __future__ import annotations

import json
import threading
import time

from websockets.exceptions import (
    ConnectionClosed,
    InvalidHandshake,
    InvalidURI,
    WebSocketException,
)
from websockets.sync.client import connect

from app.modules.provider_runtime.contracts import ProviderRequestError


class SyncWebSocketTransport:
    """Stream audio while receiving provider events on a dedicated thread."""

    def exchange(
        self,
        url: str,
        audio: bytes,
        chunk_bytes: int,
        interval_seconds: float,
        timeout_seconds: float,
    ) -> list[str]:
        messages: list[str] = []
        receive_errors: list[Exception] = []
        started = threading.Event()
        handshake_received = threading.Event()
        completed = threading.Event()
        try:
            with connect(
                url,
                open_timeout=timeout_seconds,
                close_timeout=min(timeout_seconds, 10),
                max_size=64 * 1024 * 1024,
            ) as socket:

                def receive() -> None:
                    try:
                        while not completed.is_set():
                            message = socket.recv(timeout=timeout_seconds)
                            if isinstance(message, bytes):
                                message = message.decode("utf-8")
                            messages.append(message)
                            try:
                                payload = json.loads(message)
                            except (json.JSONDecodeError, TypeError):
                                continue
                            if isinstance(payload, dict):
                                if (
                                    payload.get("action") == "started"
                                    and str(payload.get("errorCode", "0")) == "0"
                                ):
                                    started.set()
                                if (
                                    payload.get("action") in {"started", "error"}
                                    or str(payload.get("errorCode", "0")) != "0"
                                ):
                                    handshake_received.set()
                                if (
                                    payload.get("isEnd") is True
                                    or payload.get("action") == "error"
                                    or str(payload.get("errorCode", "0")) != "0"
                                ):
                                    completed.set()
                    except ConnectionClosed:
                        completed.set()
                    except (
                        WebSocketException,
                        OSError,
                        TimeoutError,
                        UnicodeDecodeError,
                    ) as error:
                        receive_errors.append(error)
                        completed.set()

                receiver = threading.Thread(
                    target=receive, name="youdao-stream-receiver", daemon=True
                )
                receiver.start()
                if not handshake_received.wait(timeout_seconds):
                    completed.set()
                    socket.close()
                    receiver.join(min(timeout_seconds, 1))
                    raise ProviderRequestError(
                        "PROVIDER_TIMEOUT", "智能翻译服务认证响应超时"
                    )
                if started.is_set():
                    for offset in range(0, len(audio), chunk_bytes):
                        if completed.is_set():
                            break
                        socket.send(audio[offset : offset + chunk_bytes])
                        if interval_seconds:
                            time.sleep(interval_seconds)
                    if not completed.is_set():
                        socket.send(b'{"end": "true"}')
                receiver.join(timeout_seconds)
                if receiver.is_alive():
                    completed.set()
                    socket.close()
                    receiver.join(min(timeout_seconds, 1))
                    raise ProviderRequestError(
                        "PROVIDER_TIMEOUT", "智能翻译服务等待结果超时"
                    )
        except ProviderRequestError:
            raise
        except (
            InvalidHandshake,
            InvalidURI,
            WebSocketException,
            OSError,
            TimeoutError,
        ):
            raise ProviderRequestError(
                "PROVIDER_TIMEOUT", "智能翻译服务连接失败或超时"
            ) from None
        if receive_errors:
            raise ProviderRequestError(
                "PROVIDER_TIMEOUT", "智能翻译服务接收结果失败"
            ) from None
        return messages
