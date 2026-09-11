from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
CSS = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")
HTML = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
SW = (ROOT / "app/static/sw.js").read_text(encoding="utf-8")


def test_ui_assets_are_cache_busted():
    assert f'/styles.css?v={VERSION}' in HTML
    assert f'/app.js?v={VERSION}' in HTML
    assert f"dpn-ai-v{VERSION}-ui-shell" in SW
    assert "dpn-ai-v10.0.0-ui-shell" not in SW


def test_sidebar_and_chat_are_explicit_scroll_regions():
    assert ".sidebar {" in CSS
    assert ".chat {" in CSS
    assert CSS.count("overflow-y: scroll;") >= 2
    assert "scrollbar-gutter: stable;" in CSS


def test_main_and_messages_are_viewport_contained():
    assert ".main {" in CSS and "overflow: hidden;" in CSS
    assert ".message-main," in CSS and "max-width: 100%;" in CSS
    assert ".message-content pre," in CSS and "overflow: auto;" in CSS


def test_compact_laptop_layout_is_present():
    assert "@media (max-height: 820px)" in CSS
    assert "@media (max-height: 650px)" in CSS
    assert "--dpn-scroll-thumb" in CSS