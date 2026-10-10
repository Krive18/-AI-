"""Subtitle text cleanup helpers."""

from __future__ import annotations

import re

_MARKDOWN_EMPHASIS = re.compile(r"\*+")
_INLINE_WHITESPACE = re.compile(r"\s+")


def clean_subtitle_text(text: str) -> str:
    """Normalize subtitle text for SRT output and on-screen display.

    LLM translators occasionally emit Markdown emphasis markers (``*`` and
    ``**``) and irregular whitespace. Every asterisk run is removed and
    inline whitespace runs collapse to a single space; line breaks are not
    expected here because subtitle segments are single lines.
    """
    return _INLINE_WHITESPACE.sub(" ", _MARKDOWN_EMPHASIS.sub("", text)).strip()
