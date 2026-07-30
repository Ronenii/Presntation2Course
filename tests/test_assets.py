import hashlib
import re
from pathlib import Path

import pytest

from p2c.theme import (
    REQUIRED_TOKENS,
    THEME_FOR_DOMAIN,
    TEMPLATE_PLACEHOLDERS,
    load_theme,
    missing_placeholders,
    missing_tokens,
)

ASSETS = Path(__file__).resolve().parents[1] / "assets"
MERMAID_SHA256 = "74d7c46dabca328c2294733910a8aa1ed0c37451776e8d5295da38a2b758fb9b"
_ABSOLUTE_URL = re.compile(r"""(?:src|href)\s*=\s*["'](?:[a-z]+:)?//""", re.IGNORECASE)
_CSS_REMOTE = re.compile(r"url\(\s*[\"']?(?:[a-z]+:)?//", re.IGNORECASE)


@pytest.mark.parametrize("name", sorted(set(THEME_FOR_DOMAIN.values())))
def test_every_mapped_theme_exists_and_is_complete(name):
    css = (ASSETS / "themes" / name / "theme.css").read_text()
    assert missing_tokens(css) == []


@pytest.mark.parametrize("name", sorted(set(THEME_FOR_DOMAIN.values())))
def test_every_mapped_theme_loads(name):
    theme = load_theme(ASSETS, name)
    assert theme.mermaid_js is not None
    assert theme.template and theme.layout_css and theme.print_css and theme.course_js


@pytest.mark.parametrize("name", sorted(set(THEME_FOR_DOMAIN.values())))
def test_themes_define_a_dark_variant(name):
    css = (ASSETS / "themes" / name / "theme.css").read_text()
    assert "prefers-color-scheme: dark" in css
    assert '[data-theme="dark"]' in css


def test_template_has_every_placeholder():
    template = (ASSETS / "base" / "template.html").read_text()
    assert missing_placeholders(template) == []


def test_template_placeholders_are_all_used_by_the_template():
    template = (ASSETS / "base" / "template.html").read_text()
    for placeholder in TEMPLATE_PLACEHOLDERS:
        assert template.count(placeholder) >= 1


@pytest.mark.parametrize(
    "relative",
    [
        "base/template.html",
        "base/layout.css",
        "base/course.js",
        "print.css",
        "themes/slate/theme.css",
        "themes/parchment/theme.css",
        "themes/clinical/theme.css",
    ],
)
def test_no_asset_reaches_the_network(relative):
    text = (ASSETS / relative).read_text()
    assert not _ABSOLUTE_URL.search(text)
    assert not _CSS_REMOTE.search(text)
    assert "@import" not in text
    assert "fetch(" not in text
    assert "XMLHttpRequest" not in text


def test_themes_use_system_font_stacks_only():
    for name in sorted(set(THEME_FOR_DOMAIN.values())):
        css = (ASSETS / "themes" / name / "theme.css").read_text()
        assert "@font-face" not in css


def test_vendored_mermaid_matches_the_pin():
    data = (ASSETS / "vendor" / "mermaid.min.js").read_bytes()
    assert hashlib.sha256(data).hexdigest() == MERMAID_SHA256
    assert data.rstrip().endswith(b'globalThis.__esbuild_esm_mermaid_nm["mermaid"].default;')


def test_course_js_drives_the_dom_contract_the_renderers_emit():
    js = (ASSETS / "base" / "course.js").read_text()
    for hook in (
        ".quiz__option",
        "data-correct",
        ".quiz__answer",
        ".quiz__why",
        ".term",
        ".term__def",
        ".mermaid",
        "theme-toggle",
        "print-pdf",
        "data-mermaid-ready",
        "IntersectionObserver",
    ):
        assert hook in js, hook
    assert "localStorage" not in js  # stateless by design


def test_the_mermaid_rerender_uses_textcontent_not_innerhtml():
    """innerHTML would re-parse an HTML-escaped diagram body as markup, undoing
    mdrender's html.escape() and executing anything embedded in the deck or research
    content that ended up inside a mermaid fence."""
    js = (ASSETS / "base" / "course.js").read_text()
    assert 'node.innerHTML = node.getAttribute("data-source")' not in js
    assert 'node.textContent = node.getAttribute("data-source")' in js


def test_layout_css_styles_every_component_the_renderers_emit():
    css = (ASSETS / "base" / "layout.css").read_text()
    for selector in (
        ".toc",
        ".quiz",
        ".quiz__option",
        ".quiz__why",
        ".term",
        ".term__def",
        ".callout--analogy",
        ".callout--prereq",
        ".callout--unverified",
        ".mermaid",
        ".glossary",
        ".diagram-fallback",
    ):
        assert selector in css, selector


def test_layout_css_only_uses_tokens_the_themes_define():
    css = (ASSETS / "base" / "layout.css").read_text()
    used = set(re.findall(r"var\((--[a-z0-9-]+)", css))
    layout_owned = {t for t in used if t.startswith(("--space", "--radius", "--measure"))}
    assert used - layout_owned <= set(REQUIRED_TOKENS)


def test_print_css_reveals_quiz_answers_and_hides_chrome():
    css = (ASSETS / "print.css").read_text()
    assert "@media print" in css
    assert ".quiz__answer" in css and ".quiz__why" in css
    assert "display: block !important" in css
    assert ".sidebar" in css


def test_layout_css_uses_logical_directional_properties_not_physical_ones():
    """Physical left/right properties don't mirror under dir="rtl"; logical
    inline-start/end properties do, so one layout.css serves both directions."""
    css = (ASSETS / "base" / "layout.css").read_text()
    for forbidden in (
        "text-align: left",
        "border-left:",
        "border-right:",
        "border-left-color:",
        "border-right-color:",
        "left: -9999px",
        "left: var(--space-4)",
        "box-shadow: inset 3px 0 0",  # physical offset instead of logical border
    ):
        assert forbidden not in css, forbidden
    for required in (
        "text-align: start",
        "border-inline-start:",
        "border-inline-end:",
        "border-inline-start-color:",
        "inset-inline-start: -9999px",
        "inset-inline-start: var(--space-4)",
    ):
        assert required in css, required


def test_print_css_has_no_physical_directional_properties():
    """Locks in the current state: print.css has nothing to mirror. If a future
    edit adds a left/right property here, this test should force a decision
    about whether it needs to become logical too."""
    css = (ASSETS / "print.css").read_text()
    for forbidden in ("text-align: left", "text-align: right", "border-left:",
                       "border-right:", "left:", "right:"):
        assert forbidden not in css, forbidden
