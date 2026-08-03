"""Property assertions for a produced course directory.

The agent half of the pipeline is non-deterministic, so it is tested by invariants rather
than snapshots. The same checker grades a real run: python3 -m p2c.invariants <output>.
"""

import re
from pathlib import Path

from p2c.build import course_basename
from p2c.mdrender import render_course
from p2c.normalize import BadDeck, pdf_page_count
from p2c.outline import load_outline, OutlineError
from p2c.theme import TEMPLATE_PLACEHOLDERS
from p2c.validate import blocking, validate_course

_TOC_HREF = re.compile(r'<a href="#([^"]+)"')
_ID = re.compile(r'\bid="([^"]+)"')
_TERM_TARGET = re.compile(r'aria-controls="(def-[^"]+)"')


def check_course(out_dir: Path, *, require_pdf: bool = False) -> list[str]:
    out_dir = Path(out_dir)
    problems: list[str] = []

    outline_path = out_dir / ".p2c" / "outline.json"
    if not outline_path.is_file():
        return [f"missing artifact: {outline_path.name} ({outline_path})"]
    try:
        outline = load_outline(outline_path)
    except OutlineError as exc:
        return [f"outline.json is invalid: {exc}"]

    # The outline's own slug decides its artifacts' shared basename (see
    # build.course_basename) -- computed here, not assumed to be "course", so this
    # checker agrees with what a real build actually names its files.
    basename = course_basename(outline["slug"])
    course_md = out_dir / f"{basename}.md"
    course_html = out_dir / f"{basename}.html"
    for path in (course_md, course_html):
        if not path.is_file():
            problems.append(f"missing artifact: {path.name} ({path})")
    if problems:
        return problems

    rendered = render_course(course_md.read_text(encoding="utf-8"))
    html_text = course_html.read_text(encoding="utf-8")

    # validate_course's network-request scan is unconditional text matching. When a
    # course has a diagram, the shipped HTML inlines the vendored mermaid bundle (always
    # the first of exactly two <script> tags right before </body>), which legitimately
    # contains ~28 inert `fetch(` calls as ordinary bundled-library code -- already
    # vetted once, at the asset level, by its own sha256 pin (see
    # test_assets.py::test_vendored_mermaid_matches_the_pin). Strip that one script
    # block before this specific call only, so course-authored content is still fully
    # checked but the vendor bundle isn't re-scanned. Mirrors build.py's approach of
    # validating a copy rendered with inline_mermaid=False, adapted for the fact that
    # check_course only has the already-shipped html_text to work with.
    validation_html = html_text
    if rendered.uses_mermaid:
        validation_html = re.sub(r"<script>.*?</script>", "", html_text, count=1, flags=re.DOTALL)

    # Everything the build already knows how to check, re-checked against what shipped.
    for finding in blocking(validate_course(rendered, outline, validation_html)):
        problems.append(f"{finding.code}: {finding.message}")

    # HTML-level integrity the markdown layer cannot see.
    for placeholder in TEMPLATE_PLACEHOLDERS:
        if placeholder in html_text:
            problems.append(
                f"unsubstituted template placeholder {placeholder} in {course_html.name}"
            )

    ids = set(_ID.findall(html_text))
    for anchor in _TOC_HREF.findall(html_text):
        if anchor not in ids:
            problems.append(f"link target #{anchor} does not exist in {course_html.name}")
    for target in _TERM_TARGET.findall(html_text):
        if target not in ids:
            problems.append(f"glossary term control points at missing {target}")

    shipped_quizzes = html_text.count('<details class="quiz"')
    if shipped_quizzes != rendered.quiz_count:
        problems.append(
            f"{course_html.name} has {shipped_quizzes} quiz blocks, {course_md.name} "
            f"renders {rendered.quiz_count}"
        )
    if rendered.quiz_count == 0:
        problems.append(f"{course_html.name} ships no quizzes at all")

    pdf = out_dir / f"{basename}.pdf"
    if require_pdf:
        if not pdf.is_file():
            problems.append(f"missing artifact: {pdf.name} ({pdf})")
        else:
            try:
                if pdf_page_count(pdf.read_bytes()) < 1:
                    problems.append(f"{pdf.name} has no pages")
            except BadDeck as exc:
                problems.append(f"{pdf.name} is unusable: {exc}")

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
