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
ANIME_SHA256 = "e8e5dc8345ef66c35ce323783e55cca518253b4f06e174b5c599941f63e66895"
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
    assert theme.anime_js is not None
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


def test_vendored_anime_matches_the_pin():
    data = (ASSETS / "vendor" / "anime.min.js").read_bytes()
    assert hashlib.sha256(data).hexdigest() == ANIME_SHA256
    assert b"anime.js" in data[:200]
    assert b"Julian Garnier" in data[:200]


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
        ".anim__timeline",
        "wireAnimations",
        "prefers-reduced-motion",
        "createTimeline",
        "step.duration",
        "step.ease",
        "path-segment",
        "set-attr",
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


def test_course_js_wires_the_sidebar_drawer():
    js = (ASSETS / "base" / "course.js").read_text()
    for hook in ("sidebar-toggle", "sidebar-scrim", "data-open", "wireSidebarToggle"):
        assert hook in js, hook
    assert "localStorage" not in js  # drawer state stays non-persistent, same as today


def test_course_js_wires_the_diagram_lightbox():
    js = (ASSETS / "base" / "course.js").read_text()
    for hook in (
        "wireDiagramZoom",
        "diagram-lightbox",
        "diagram-lightbox-stage",
        "diagram-zoom-in",
        "diagram-zoom-out",
        "diagram-zoom-reset",
        "diagram-lightbox-close",
        "pointerdown",
        "pointermove",
        "pointerup",
        "beforeprint",
    ):
        assert hook in js, hook


def test_the_lightbox_fits_the_diagram_to_the_stage_instead_of_opening_at_scale_1():
    """A diagram's natural size is usually a few hundred px, far smaller than a
    full-screen stage -- opening at a hardcoded scale of 1 would show it at the
    same small size it already had inline, defeating the point of a lightbox."""
    js = (ASSETS / "base" / "course.js").read_text()
    assert "var fitScale = 1;" in js
    assert 'svg.getBoundingClientRect()' in js or "diagram.querySelector(\"svg\")" in js
    assert "scale = fitScale" in js
    assert "scale = 1; x = 0; y = 0;" not in js  # the old hardcoded reset


def test_the_lightbox_measures_natural_size_after_unhiding_not_before():
    """The stage is display:none while the lightbox has [hidden] -- measuring
    its size before clearing that attribute would read back a 0x0 rect, making
    every fitScale computation divide by zero-derived nonsense."""
    js = (ASSETS / "base" / "course.js").read_text()
    open_start = js.index("function open(diagram) {")
    open_body = js[open_start : js.index("\n    function close()", open_start)]
    unhide_index = open_body.index("lightbox.hidden = false;")
    measure_index = open_body.index("stage.getBoundingClientRect()")
    assert unhide_index < measure_index


def test_the_lightbox_backdrop_is_fully_opaque():
    """Even a high alpha like 0.85-0.96 still lets sharp text edges from the
    page behind show through faintly -- looks like a stacking bug even though
    it's just alpha math. The backdrop must be fully solid, not translucent."""
    css = (ASSETS / "base" / "layout.css").read_text()
    rule_start = css.index(".diagram-lightbox {")
    rule = css[rule_start : css.index("}", rule_start)]
    assert "rgba(" not in rule
    assert "background: #000;" in rule


def test_the_lightbox_restores_the_diagram_to_its_original_parent_on_close():
    """The moved-in .mermaid div must return to the content flow on close, not
    stay stranded in the lightbox -- renderDiagrams() re-populates whatever
    .mermaid nodes it finds anywhere in the document on every theme toggle, so a
    diagram left behind in a hidden lightbox would silently vanish from the
    page's normal reading flow."""
    js = (ASSETS / "base" / "course.js").read_text()
    assert "homeParent.insertBefore(current, homeNext)" in js
    assert "homeParent.appendChild(current)" in js


def test_term_def_popup_has_a_minimum_width():
    """Bug: .term__def is absolutely positioned with only max-inline-size set, no
    minimum -- a short definition (a few words) shrinks the popup to fit its own
    content, wrapping nearly every word onto its own line. A sensible floor fixes
    this without changing the existing max-width ceiling or the mobile override.
    """
    css = (ASSETS / "base" / "layout.css").read_text()
    assert "min-inline-size: min(16rem, calc(100vw - 2 * var(--space-4)))" in css


def test_the_lightbox_closes_before_print():
    """print.css hides .diagram-lightbox outright; without closing first, a
    diagram open at print time would be missing from the printed page entirely
    instead of appearing back in its normal position."""
    js = (ASSETS / "base" / "course.js").read_text()
    assert 'window.addEventListener("beforeprint", close)' in js
    css = (ASSETS / "print.css").read_text()
    assert ".diagram-lightbox { display: none !important; }" in css


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
        ".diagram-lightbox",
        ".diagram-lightbox__toolbar",
        ".diagram-lightbox__stage",
        ".glossary",
        ".sources-group",
        ".sources",
        ".diagram-fallback",
        ".anim__caption",
        ".anim--array-ops",
        ".anim__array",
        ".anim__array-axis",
        ".anim__array-gridline",
        ".anim__array-label",
        ".anim__array-legend",
        ".anim__array-steps-static",
        ".anim--path-trace",
        ".anim__path",
        ".anim__path-axis",
        ".anim__path-tick",
        ".anim__path-line",
        ".anim__path-marker",
        ".anim__path-trail",
        ".anim__path-caption",
        ".anim__path-steps-static",
    ):
        assert selector in css, selector


def test_layout_css_only_uses_tokens_the_themes_define():
    css = (ASSETS / "base" / "layout.css").read_text()
    used = set(re.findall(r"var\((--[a-z0-9-]+)", css))
    layout_owned = {
        t
        for t in used
        if t.startswith((
            "--space", "--radius", "--measure", "--z-", "--drawer-closed-x",
            "--anim-array-",
        ))
    }
    assert used - layout_owned <= set(REQUIRED_TOKENS)


def test_caption_hiding_is_scoped_to_array_ops_so_authored_captions_survive():
    """Array-ops and path-trace share .anim__caption, but they hold different kinds
    of text. Array-ops' caption is generated chrome ("Step 1 of 3") that means
    nothing once frozen, so print and reduced motion hide it. Path-trace's caption
    is the course author's OWN written text (anim.caption) -- real content, which a
    bare `.anim__caption { display: none }` silently deleted from every printout and
    from every reduced-motion reader's page. Both hiding rules must therefore be
    scoped to .anim--array-ops.
    """
    for name in (ASSETS / "base" / "layout.css", ASSETS / "print.css"):
        css = name.read_text()
        hide_rules = re.findall(r"^\s*([^\n{]*\.anim__caption[^\n{]*)\{[^}]*display:\s*none",
                                css, re.MULTILINE)
        assert hide_rules, f"{name.name}: no .anim__caption hiding rule found at all"
        for selector in hide_rules:
            assert ".anim--array-ops" in selector, f"{name.name}: unscoped hide {selector!r}"


def test_print_css_reveals_quiz_answers_and_hides_chrome():
    css = (ASSETS / "print.css").read_text()
    assert "@media print" in css
    assert ".quiz__answer" in css and ".quiz__why" in css
    assert "display: block !important" in css
    assert ".sidebar" in css


def test_print_css_isolates_printed_urls_from_bidi_reordering():
    """The injected '(' url ')' after a printed link is itself always LTR content;
    without an explicit isolate the bidi algorithm would reorder the parentheses
    around it on an RTL-printed page."""
    css = (ASSETS / "print.css").read_text()
    rule_start = css.index('a[href^="http"]')
    rule = css[rule_start : css.index("}", rule_start)]
    assert "unicode-bidi: isolate" in rule
    assert "direction: ltr" in rule


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


def test_layout_css_has_no_four_value_margin_or_padding_shorthand():
    """A 4-value margin/padding shorthand (top right bottom left) is inherently
    asymmetric and physical -- its last value is always a physical left/right
    margin/padding that never mirrors under dir="rtl". The substring-based logical-
    properties test above only catches longhand physical property names
    (border-left, text-align: left, ...), so it never noticed .toc__topics's
    `margin: var(--space-1) 0 var(--space-4) var(--space-3)` -- a shorthand whose
    fourth value is a bare margin-left with no logical equivalent in shorthand form.
    This test catches that class of miss directly, by parsing the actual values."""
    css = (ASSETS / "base" / "layout.css").read_text()
    for match in re.finditer(r"(?<![-\w])(margin|padding):\s*([^;]+);", css):
        prop, value = match.group(1), match.group(2)
        tokens = value.split()
        assert len(tokens) != 4, (
            f"{prop}: {value} is a 4-value shorthand -- inherently physical, "
            "convert to margin-block/margin-inline (or padding-block/padding-inline)"
        )


def test_print_css_has_no_physical_directional_properties():
    """Locks in the current state: print.css has nothing to mirror. If a future
    edit adds a left/right property here, this test should force a decision
    about whether it needs to become logical too."""
    css = (ASSETS / "print.css").read_text()
    for forbidden in ("text-align: left", "text-align: right", "border-left:",
                       "border-right:", "left:", "right:"):
        assert forbidden not in css, forbidden


def test_content_column_is_centered_within_its_grid_track():
    css = (ASSETS / "base" / "layout.css").read_text()
    rule_start = css.index(".content {")
    rule = css[rule_start : css.index("}", rule_start)]
    assert "margin-inline: auto" in rule


def test_template_has_a_sidebar_toggle_and_scrim():
    template = (ASSETS / "base" / "template.html").read_text()
    assert 'id="sidebar-toggle"' in template
    assert 'aria-controls="sidebar"' in template
    assert 'id="sidebar"' in template
    assert 'id="sidebar-scrim"' in template
    assert 'class="sidebar-scrim"' in template


def test_layout_css_styles_the_mobile_drawer():
    css = (ASSETS / "base" / "layout.css").read_text()
    for selector in (".sidebar-toggle", ".sidebar-scrim", "--z-scrim", "--z-drawer", "--z-popover"):
        assert selector in css, selector


def test_template_has_a_diagram_lightbox():
    template = (ASSETS / "base" / "template.html").read_text()
    for hook in (
        'id="diagram-lightbox"',
        'id="diagram-lightbox-stage"',
        'id="diagram-zoom-in"',
        'id="diagram-zoom-out"',
        'id="diagram-zoom-reset"',
        'id="diagram-lightbox-close"',
    ):
        assert hook in template, hook


def test_layout_css_stacks_the_lightbox_above_every_other_overlay():
    css = (ASSETS / "base" / "layout.css").read_text()
    assert "--z-lightbox: 50" in css
    rule_start = css.index(".diagram-lightbox {")
    rule = css[rule_start : css.index("}", rule_start)]
    assert "var(--z-lightbox)" in rule


def test_sidebar_drawer_transform_is_direction_aware():
    css = (ASSETS / "base" / "layout.css").read_text()
    assert "--drawer-closed-x: -100%" in css
    assert '[dir="rtl"]' in css
    assert "--drawer-closed-x: 100%" in css


def test_print_css_hides_the_sidebar_scrim():
    css = (ASSETS / "print.css").read_text()
    assert ".sidebar-scrim" in css


def test_term_def_is_positioned_out_of_flow_not_a_block_sibling():
    css = (ASSETS / "base" / "layout.css").read_text()
    rule_start = css.index(".term__def {")
    rule = css[rule_start : css.index("}", rule_start)]
    assert "position: absolute" in rule
    assert "max-inline-size:" in rule


def test_print_css_returns_the_term_definition_to_normal_flow():
    css = (ASSETS / "print.css").read_text()
    rule_start = css.index(".term__def {")
    rule = css[rule_start : css.index("}", rule_start)]
    assert "position: static !important" in rule


def test_course_js_closes_other_open_terms_and_supports_escape():
    js = (ASSETS / "base" / "course.js").read_text()
    assert "Escape" in js
    # wireTerms must reference more than one .term__def when opening one, i.e. it
    # iterates all defs to close siblings -- lock in the query used for that.
    assert js.count('querySelectorAll(".term__def")') >= 1 or js.count('querySelectorAll(".term")') >= 1
