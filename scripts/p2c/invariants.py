"""Property assertions for a produced course directory.

The agent half of the pipeline is non-deterministic, so it is tested by invariants rather
than snapshots. The same checker grades a real run: python3 -m p2c.invariants <output>.
"""

import re
from pathlib import Path

from p2c.mdrender import render_course
from p2c.normalize import BadDeck, pdf_page_count
from p2c.outline import load_outline
from p2c.theme import TEMPLATE_PLACEHOLDERS
from p2c.validate import blocking, validate_course

_TOC_HREF = re.compile(r'<a href="#([^"]+)"')
_ID = re.compile(r'\bid="([^"]+)"')
_TERM_TARGET = re.compile(r'aria-controls="(def-[^"]+)"')


def check_course(out_dir: Path, *, require_pdf: bool = False) -> list[str]:
    out_dir = Path(out_dir)
    problems: list[str] = []

    course_md = out_dir / "course.md"
    course_html = out_dir / "course.html"
    outline_path = out_dir / ".p2c" / "outline.json"
    for path in (course_md, course_html, outline_path):
        if not path.is_file():
            problems.append(f"missing artifact: {path.name} ({path})")
    if problems:
        return problems

    outline = load_outline(outline_path)
    rendered = render_course(course_md.read_text(encoding="utf-8"))
    html_text = course_html.read_text(encoding="utf-8")

    # Everything the build already knows how to check, re-checked against what shipped.
    for finding in blocking(validate_course(rendered, outline, html_text)):
        problems.append(f"{finding.code}: {finding.message}")

    # HTML-level integrity the markdown layer cannot see.
    for placeholder in TEMPLATE_PLACEHOLDERS:
        if placeholder in html_text:
            problems.append(f"unsubstituted template placeholder {placeholder} in course.html")

    ids = set(_ID.findall(html_text))
    for anchor in _TOC_HREF.findall(html_text):
        if anchor not in ids:
            problems.append(f"link target #{anchor} does not exist in course.html")
    for target in _TERM_TARGET.findall(html_text):
        if target not in ids:
            problems.append(f"glossary term control points at missing {target}")

    shipped_quizzes = html_text.count('<div class="quiz"')
    if shipped_quizzes != rendered.quiz_count:
        problems.append(
            f"course.html has {shipped_quizzes} quiz blocks, course.md renders "
            f"{rendered.quiz_count}"
        )
    if rendered.quiz_count == 0:
        problems.append("course.html ships no quizzes at all")

    pdf = out_dir / "course.pdf"
    if require_pdf:
        if not pdf.is_file():
            problems.append(f"missing artifact: course.pdf ({pdf})")
        else:
            try:
                if pdf_page_count(pdf.read_bytes()) < 1:
                    problems.append("course.pdf has no pages")
            except BadDeck as exc:
                problems.append(f"course.pdf is unusable: {exc}")

    return problems


def main(argv: list[str]) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(prog="p2c.invariants")
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--require-pdf", action="store_true")
    args = parser.parse_args(argv)

    problems = check_course(args.out_dir, require_pdf=args.require_pdf)
    print(json.dumps({"sound": not problems, "problems": problems}, indent=2))
    return 3 if problems else 0


if __name__ == "__main__":
    import sys

    sys.exit(main(sys.argv[1:]))
