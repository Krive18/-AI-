from types import TracebackType
from typing import Self
from urllib.error import HTTPError

import pytest

from app.modules.provider_runtime import http
from app.modules.provider_runtime.contracts import ProviderRequestError


class _Response:
    def __init__(self, status_code: str) -> None:
        self.headers = {"X-Api-Status-Code": status_code}

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def read(self) -> bytes:
        return b"{}"


def test_doubao_business_error_header_is_not_reported_as_connected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        http, "urlopen", lambda *_args, **_kwargs: _Response("45000000")
    )

    with pytest.raises(ProviderRequestError, match="PROVIDER_REJECTED"):
        http.UrlLibJsonTransport().post_json(
            "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit",
            {},
            {},
            1,
        )


def test_doubao_silent_probe_has_a_specific_safe_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        http, "urlopen", lambda *_args, **_kwargs: _Response("20000003")
    )

    with pytest.raises(ProviderRequestError) as caught:
        http.UrlLibJsonTransport().post_json(
            "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit",
            {},
            {},
            1,
        )

    assert caught.value.code == "PROVIDER_NO_SPEECH"


def test_doubao_missing_resource_permission_is_not_mislabeled_as_bad_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_error = HTTPError(
        "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit",
        403,
        "Forbidden",
        {
            "X-Api-Status-Code": "45000030",
            "X-Api-Message": "requested resource not granted",
        },
        None,
    )

    def raise_error(*_args: object, **_kwargs: object) -> None:
        raise response_error

    monkeypatch.setattr(http, "urlopen", raise_error)

    with pytest.raises(ProviderRequestError) as caught:
        http.UrlLibJsonTransport().post_json(
            "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit",
            {},
            {},
            1,
        )

    assert caught.value.code == "PROVIDER_RESOURCE_NOT_GRANTED"
