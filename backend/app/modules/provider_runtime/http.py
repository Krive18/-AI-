from __future__ import annotations

import json
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.modules.provider_runtime.contracts import JsonTransport, ProviderRequestError


class UrlLibJsonTransport(JsonTransport):
    """Small synchronous transport for worker processes; callers set a per-version timeout."""

    def post_json(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> dict[str, object]:
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                self._validate_provider_status(response.headers)
                decoded = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if error.headers.get("X-Api-Status-Code") == "45000030":
                raise ProviderRequestError(
                    "PROVIDER_RESOURCE_NOT_GRANTED",
                    "语音识别资源未授权，请核对已开通服务与资源 ID",
                ) from None
            if error.code in (401, 403):
                raise ProviderRequestError(
                    "PROVIDER_AUTH_FAILED", "供应商认证失败"
                ) from None
            if error.code == 429:
                raise ProviderRequestError(
                    "PROVIDER_RATE_LIMITED", "供应商请求受限"
                ) from None
            raise ProviderRequestError("PROVIDER_HTTP_ERROR") from None
        except (TimeoutError, URLError):
            raise ProviderRequestError(
                "PROVIDER_TIMEOUT", "供应商请求超时或不可用"
            ) from None
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ProviderRequestError(
                "PROVIDER_RESPONSE_INVALID", "供应商响应无效"
            ) from None
        if not isinstance(decoded, dict):
            raise ProviderRequestError("PROVIDER_RESPONSE_INVALID", "供应商响应无效")
        return cast(dict[str, object], decoded)

    @staticmethod
    def _validate_provider_status(headers: object) -> None:
        getter = getattr(headers, "get", None)
        status = getter("X-Api-Status-Code") if callable(getter) else None
        if status == "20000003":
            raise ProviderRequestError("PROVIDER_NO_SPEECH", "识别音频中没有检测到语音")
        if status and status not in {"20000000", "20000001", "20000002"}:
            raise ProviderRequestError(
                "PROVIDER_REJECTED", "供应商拒绝了请求，请核对权限和参数"
            )

    def get_json(
        self,
        url: str,
        headers: dict[str, str],
        query: dict[str, str],
        timeout_seconds: float,
    ) -> dict[str, object]:
        data = self._get(url, headers, query, timeout_seconds)
        try:
            decoded = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ProviderRequestError(
                "PROVIDER_RESPONSE_INVALID", "供应商响应无效"
            ) from None
        if not isinstance(decoded, dict):
            raise ProviderRequestError("PROVIDER_RESPONSE_INVALID", "供应商响应无效")
        return cast(dict[str, object], decoded)

    def get_bytes(
        self,
        url: str,
        headers: dict[str, str],
        query: dict[str, str],
        timeout_seconds: float,
    ) -> bytes:
        return self._get(url, headers, query, timeout_seconds)

    def delete_json(
        self,
        url: str,
        headers: dict[str, str],
        timeout_seconds: float,
    ) -> dict[str, object]:
        request = Request(url, headers=headers, method="DELETE")
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except HTTPError as error:
            if error.code in (401, 403):
                raise ProviderRequestError(
                    "PROVIDER_AUTH_FAILED", "供应商认证失败"
                ) from None
            raise ProviderRequestError("PROVIDER_HTTP_ERROR") from None
        except (TimeoutError, URLError):
            raise ProviderRequestError(
                "PROVIDER_TIMEOUT", "供应商请求超时或不可用"
            ) from None
        if not body.strip():
            return {}
        try:
            decoded = json.loads(body)
        except json.JSONDecodeError:
            raise ProviderRequestError(
                "PROVIDER_RESPONSE_INVALID", "供应商响应无效"
            ) from None
        if not isinstance(decoded, dict):
            raise ProviderRequestError("PROVIDER_RESPONSE_INVALID", "供应商响应无效")
        return cast(dict[str, object], decoded)

    def _get(
        self,
        url: str,
        headers: dict[str, str],
        query: dict[str, str],
        timeout_seconds: float,
    ) -> bytes:
        suffix = urlencode(query)
        request = Request(
            f"{url}?{suffix}" if suffix else url, headers=headers, method="GET"
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                return cast(bytes, response.read())
        except HTTPError as error:
            if error.code in (401, 403):
                raise ProviderRequestError(
                    "PROVIDER_AUTH_FAILED", "供应商认证失败"
                ) from None
            raise ProviderRequestError("PROVIDER_HTTP_ERROR") from None
        except (TimeoutError, URLError):
            raise ProviderRequestError(
                "PROVIDER_TIMEOUT", "供应商请求超时或不可用"
            ) from None
