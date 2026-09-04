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


def test_sidebar_and_chat_are_explicit_scroll_regions():
    hotfix = CSS.split("/* DPN AI v5.0.5 viewport and scrolling hotfix */", 1)[1]
    assert ".sidebar" in hotfix and "overflow-y: scroll" in hotfix
    assert ".chat" in hotfix and "overflow-y: scroll" in hotfix
    assert "scrollbar-gutter: stable" in hotfix


def test_main_and_messages_are_viewport_contained():
    hotfix = CSS.split("/* DPN AI v5.0.5 viewport and scrolling hotfix */", 1)[1]
    assert ".main" in hotfix and "overflow: hidden" in hotfix
    assert ".message-main" in hotfix and "max-width: 100%" in hotfix
    assert ".message-content pre" in hotfix and "overflow: auto" in hotfix


def test_compact_laptop_layout_is_present():
    assert "@media (max-height: 820px)" in CSS
    assert "@media (max-height: 650px)" in CSS
    assert "--dpn-scroll-thumb" in CSS