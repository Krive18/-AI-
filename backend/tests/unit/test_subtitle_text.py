from app.modules.translation.subtitle_text import clean_subtitle_text


def test_clean_subtitle_text_removes_markdown_emphasis() -> None:
    assert clean_subtitle_text("**Hello** world") == "Hello world"
    assert clean_subtitle_text("*Hello* *world*") == "Hello world"


def test_clean_subtitle_text_collapses_inline_whitespace() -> None:
    assert clean_subtitle_text("Hello    \t world") == "Hello world"
    assert clean_subtitle_text("  padded text  ") == "padded text"


def test_clean_subtitle_text_keeps_plain_text_unchanged() -> None:
    assert clean_subtitle_text("Xin chào thế giới") == "Xin chào thế giới"
    assert clean_subtitle_text("") == ""
