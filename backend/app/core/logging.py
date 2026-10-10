import logging
from contextvars import ContextVar

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO)
