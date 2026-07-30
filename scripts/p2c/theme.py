"""Theme selection and asset loading.

subject_domain drives theme choice and nothing else. Layout lives in base/, tokens live
in themes/<name>/theme.css, and a theme that forgets a token fails to load rather than
shipping a half-styled course.
"""

import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_THEME = "slate"
THEME_FOR_DOMAIN = {
    "systems": "slate",
    "theory": "parchment",
    "life-sciences": "clinical",
    "other": "slate",
}

RTL_LANGUAGES = frozenset({"ar", "dv", "fa", "he", "ps", "sd", "ur", "yi"})


def is_rtl(code: str) -> bool:
    return code.lower() in RTL_LANGUAGES

REQUIRED_TOKENS = (
    "--font-body",
    "--font-heading",
    "--font-mono",
    "--color-bg",
    "--color-surface",
    "--color-fg",
    "--color-muted",
    "--color-border",
    "--color-accent",
    "--color-accent-contrast",
    "--color-analogy",
    "--color-prereq",
    "--color-warn",
    "--color-correct",
    "--color-incorrect",
    "--mermaid-primary",
    "--mermaid-secondary",
    "--mermaid-line",
    "--mermaid-text",
)

TEMPLATE_PLACEHOLDERS = (
    "{{TITLE}}",
    "{{THEME_NAME}}",
    "{{THEME_CSS}}",
    "{{LAYOUT_CSS}}",
    "{{PRINT_CSS}}",
    "{{TOC}}",
    "{{CONTENT}}",
    "{{GLOSSARY}}",
    "{{SOURCE_DECKS}}",
    "{{MERMAID_JS}}",
    "{{COURSE_JS}}",
    "{{LANG}}",
    "{{DIR}}",
)


class ThemeError(Exception):
    """The requested theme cannot be loaded."""


@dataclass
class Theme:
    name: str
    theme_css: str
    layout_css: str
    print_css: str
    course_js: str
    template: str
    mermaid_js: str | None


def theme_for(domain: str | None) -> str:
    """Unknown or missing domains fall back to the default rather than failing."""
    return THEME_FOR_DOMAIN.get(domain or "", DEFAULT_THEME)


def missing_tokens(css: str) -> list[str]:
    # Strip CSS comments before checking for tokens to avoid false positives
    # (token names in comments do not count as defined)
    css_no_comments = re.sub(r'/\*.*?\*/', '', css, flags=re.DOTALL)
    return [t for t in REQUIRED_TOKENS if not re.search(rf"{re.escape(t)}\s*:", css_no_comments)]


def missing_placeholders(template: str) -> list[str]:
    return [p for p in TEMPLATE_PLACEHOLDERS if p not in template]


def available_themes(assets_dir: Path) -> list[str]:
    themes = Path(assets_dir) / "themes"
    if not themes.is_dir():
        return []
    return sorted(d.name for d in themes.iterdir() if (d / "theme.css").is_file())


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ThemeError(f"missing asset {path.name}: {exc}") from exc


def load_theme(assets_dir: Path, name: str) -> Theme:
    assets = Path(assets_dir)
    theme_dir = assets / "themes" / name
    if not (theme_dir / "theme.css").is_file():
        raise ThemeError(
            f"unknown theme {name!r}; available: {available_themes(assets) or 'none'}"
        )
    theme_css = _read(theme_dir / "theme.css")
    absent = missing_tokens(theme_css)
    if absent:
        raise ThemeError(f"theme {name!r} does not define: {', '.join(absent)}")

    override = theme_dir / "template.html"
    template = _read(override if override.is_file() else assets / "base" / "template.html")
    mermaid = assets / "vendor" / "mermaid.min.js"
    return Theme(
        name=name,
        theme_css=theme_css,
        layout_css=_read(assets / "base" / "layout.css"),
        print_css=_read(assets / "print.css"),
        course_js=_read(assets / "base" / "course.js"),
        template=template,
        mermaid_js=mermaid.read_text(encoding="utf-8") if mermaid.is_file() else None,
    )
