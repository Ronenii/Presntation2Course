import pytest

from p2c.theme import (
    DEFAULT_THEME,
    REQUIRED_TOKENS,
    THEME_FOR_DOMAIN,
    Theme,
    ThemeError,
    available_themes,
    load_theme,
    missing_tokens,
    theme_for,
)


def test_domain_mapping_matches_the_design():
    assert THEME_FOR_DOMAIN == {
        "systems": "slate",
        "theory": "parchment",
        "life-sciences": "clinical",
        "other": "slate",
    }
    assert DEFAULT_THEME == "slate"


@pytest.mark.parametrize(
    "domain,expected",
    [
        ("systems", "slate"),
        ("theory", "parchment"),
        ("life-sciences", "clinical"),
        ("other", "slate"),
        ("nonsense", "slate"),
        (None, "slate"),
    ],
)
def test_theme_for_never_fails(domain, expected):
    assert theme_for(domain) == expected


def _complete_css():
    return ":root {\n" + "\n".join(f"  {t}: x;" for t in REQUIRED_TOKENS) + "\n}\n"


def test_missing_tokens_is_empty_for_a_complete_theme():
    assert missing_tokens(_complete_css()) == []


def test_missing_tokens_lists_what_is_absent():
    css = _complete_css().replace(f"{REQUIRED_TOKENS[0]}: x;", "")
    assert missing_tokens(css) == [REQUIRED_TOKENS[0]]


def test_missing_tokens_ignores_tokens_in_comments():
    # Token names in comments do not count as defined; this test ensures
    # that a token noted in a TODO comment but never actually declared
    # is still reported as missing (critical for authoring checks in Task 12)
    token_to_hide = REQUIRED_TOKENS[0]
    other_tokens = [t for t in REQUIRED_TOKENS if t != token_to_hide]
    css = f"/* TODO: define {token_to_hide} later */\n:root {{\n"
    css += "\n".join(f"  {t}: x;" for t in other_tokens)
    css += "\n}\n"
    assert missing_tokens(css) == [token_to_hide]


def _assets(tmp_path, *, theme="slate", tokens=True, template_override=None):
    base = tmp_path / "base"
    base.mkdir(parents=True)
    (base / "layout.css").write_text(".shell { display: grid; }")
    (base / "course.js").write_text("// course")
    (base / "template.html").write_text("<main>{{CONTENT}}</main>")
    (tmp_path / "print.css").write_text("@media print { body { color: black; } }")
    theme_dir = tmp_path / "themes" / theme
    theme_dir.mkdir(parents=True)
    css = _complete_css() if tokens else ":root { --color-bg: white; }"
    (theme_dir / "theme.css").write_text(css)
    if template_override is not None:
        (theme_dir / "template.html").write_text(template_override)
    return tmp_path


def test_load_theme_reads_base_and_theme_files(tmp_path):
    theme = load_theme(_assets(tmp_path), "slate")
    assert isinstance(theme, Theme)
    assert theme.name == "slate"
    assert "--color-bg" in theme.theme_css
    assert theme.layout_css == ".shell { display: grid; }"
    assert theme.course_js == "// course"
    assert theme.template == "<main>{{CONTENT}}</main>"
    assert "@media print" in theme.print_css
    assert theme.mermaid_js is None


def test_load_theme_prefers_a_per_theme_template_override(tmp_path):
    assets = _assets(tmp_path, template_override="<article>{{CONTENT}}</article>")
    assert load_theme(assets, "slate").template == "<article>{{CONTENT}}</article>"


def test_load_theme_reads_vendored_mermaid_when_present(tmp_path):
    assets = _assets(tmp_path)
    vendor = assets / "vendor"
    vendor.mkdir()
    (vendor / "mermaid.min.js").write_text("globalThis.mermaid = {};")
    assert load_theme(assets, "slate").mermaid_js == "globalThis.mermaid = {};"


def test_load_theme_rejects_an_unknown_theme(tmp_path):
    with pytest.raises(ThemeError, match="unknown theme 'nope'"):
        load_theme(_assets(tmp_path), "nope")


def test_load_theme_rejects_a_theme_missing_tokens(tmp_path):
    with pytest.raises(ThemeError, match="--font-body"):
        load_theme(_assets(tmp_path, tokens=False), "slate")


def test_load_theme_reports_a_missing_base_file(tmp_path):
    assets = _assets(tmp_path)
    (assets / "base" / "course.js").unlink()
    with pytest.raises(ThemeError, match="course.js"):
        load_theme(assets, "slate")


def test_available_themes_is_sorted(tmp_path):
    assets = _assets(tmp_path)
    for extra in ("parchment", "clinical"):
        d = assets / "themes" / extra
        d.mkdir()
        (d / "theme.css").write_text(_complete_css())
    assert available_themes(assets) == ["clinical", "parchment", "slate"]
