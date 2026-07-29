"""Phase 4: course.md -> course.html, then validate.

Deterministic and side-effect-free apart from the files it writes: same inputs, byte-identical
output. No timestamps anywhere, so reruns diff cleanly and the golden test is meaningful.
"""

import html
import json
import re
from dataclasses import dataclass
from pathlib import Path

from p2c.assemble import assemble
from p2c.mdrender import Rendered, render_course
from p2c.outline import load_outline
from p2c.theme import Theme, load_theme, theme_for
from p2c.validate import Finding, blocking, findings_to_json, validate_course

_PLACEHOLDER_RE = re.compile(r"\{\{[A-Z_]+\}\}")


@dataclass
class BuildResult:
    course_md: Path
    course_html: Path
    findings_path: Path
    theme: str
    findings: list[Finding]
    rendered: Rendered


def fill_template(
    theme: Theme,
    rendered: Rendered,
    *,
    title: str,
    source_decks: list[str],
    inline_mermaid: bool,
) -> str:
    decks = ", ".join(source_decks) if source_decks else "the source deck"
    substitutions = {
        "{{TITLE}}": html.escape(title),
        "{{THEME_NAME}}": theme.name,
        "{{THEME_CSS}}": theme.theme_css,
        "{{LAYOUT_CSS}}": theme.layout_css,
        "{{PRINT_CSS}}": theme.print_css,
        "{{TOC}}": rendered.toc_html,
        "{{CONTENT}}": rendered.html_body,
        "{{GLOSSARY}}": rendered.glossary_html or "<p>No jargon was recorded.</p>",
        "{{SOURCE_DECKS}}": html.escape(decks),
        "{{MERMAID_JS}}": theme.mermaid_js if (inline_mermaid and theme.mermaid_js) else "",
        "{{COURSE_JS}}": theme.course_js,
    }
    # One pass, so substituted CSS/JS/prose can never itself be treated as a placeholder.
    return _PLACEHOLDER_RE.sub(
        lambda m: substitutions.get(m.group(0), m.group(0)), theme.template
    )


def build(
    outline_path: Path,
    modules_dir: Path,
    out_dir: Path,
    assets_dir: Path,
    theme: str | None = None,
) -> BuildResult:
    outline = load_outline(Path(outline_path))
    course_md_text = assemble(outline, Path(modules_dir))

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    course_md = out_dir / "course.md"
    course_md.write_text(course_md_text, encoding="utf-8")

    rendered = render_course(course_md_text)
    theme_name = theme or rendered.front_matter.theme or theme_for(outline["subject_domain"])
    loaded = load_theme(Path(assets_dir), theme_name)

    html_text = fill_template(
        loaded,
        rendered,
        title=outline["title"],
        source_decks=rendered.front_matter.source_decks,
        inline_mermaid=rendered.uses_mermaid,
    )
    course_html = out_dir / "course.html"
    course_html.write_text(html_text, encoding="utf-8")

    # Validate against a copy that never inlines the vendored mermaid bundle. That
    # bundle is pinned by its own SHA256 (see test_assets.py::test_vendored_mermaid_
    # matches_the_pin) and is explicitly exempted from the assets-level "no network
    # reach" check because it legitimately contains inert `fetch(` calls as bundled
    # library code. validate_course's external_request scan is unconditional text
    # matching, so scanning the real, mermaid-inlined html_text would report ~28
    # false-positive blocking findings on every course that has a single diagram.
    # The vendor file's own content is already vetted once, at the asset level, and
    # cannot vary per course, so re-scanning it on every build adds no value -- only
    # course-authored/theme-boilerplate content needs checking here.
    validation_html = fill_template(
        loaded,
        rendered,
        title=outline["title"],
        source_decks=rendered.front_matter.source_decks,
        inline_mermaid=False,
    )
    findings = validate_course(rendered, outline, validation_html)
    findings_path = out_dir / ".p2c" / "review" / "build-findings.json"
    findings_path.parent.mkdir(parents=True, exist_ok=True)
    findings_path.write_text(
        json.dumps(findings_to_json(findings), indent=2) + "\n", encoding="utf-8"
    )

    return BuildResult(
        course_md=course_md,
        course_html=course_html,
        findings_path=findings_path,
        theme=theme_name,
        findings=findings,
        rendered=rendered,
    )


def main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="build", description="Render course.md into a self-contained course.html."
    )
    parser.add_argument("--outline", required=True, type=Path)
    parser.add_argument("--modules", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--assets", type=Path, default=Path(__file__).resolve().parents[2] / "assets"
    )
    parser.add_argument("--theme", default=None)
    args = parser.parse_args(argv)

    result = build(args.outline, args.modules, args.out, args.assets, args.theme)
    summary = {
        "course_md": str(result.course_md),
        "course_html": str(result.course_html),
        "findings": str(result.findings_path),
        "theme": result.theme,
        "topics": len(result.rendered.topic_ids),
        "quiz_count": result.rendered.quiz_count,
        "uses_mermaid": result.rendered.uses_mermaid,
        "glossary_terms": len(result.rendered.glossary),
        "blocking": findings_to_json(blocking(result.findings)),
        "noted": findings_to_json([f for f in result.findings if not f.blocking]),
    }
    print(json.dumps(summary, indent=2))
    return 3 if blocking(result.findings) else 0
