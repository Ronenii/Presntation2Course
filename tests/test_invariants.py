import json
import os
from pathlib import Path

import pytest

from fixtures.make_fixtures import make_pdf
from p2c.build import build, course_basename
from p2c.invariants import check_course

REPO = Path(__file__).resolve().parents[1]
MINI = REPO / "tests" / "fixtures" / "mini-course"
ASSETS = REPO / "assets"
MINI_HE = REPO / "tests" / "fixtures" / "mini-course-he"


MINI_BASENAME = course_basename(json.loads((MINI / "outline.json").read_text())["title"])


@pytest.fixture
def course_dir(tmp_path):
    normalized = tmp_path / ".p2c" / "normalized"
    normalized.mkdir(parents=True)
    (normalized / "terse.pdf").write_bytes((REPO / "tests" / "fixtures" / "terse.pdf").read_bytes())
    build(MINI / "outline.json", MINI / "modules", tmp_path, ASSETS)
    (tmp_path / ".p2c" / "outline.json").write_text((MINI / "outline.json").read_text())
    return tmp_path


@pytest.fixture
def course_dir_he(tmp_path):
    normalized = tmp_path / ".p2c" / "normalized"
    normalized.mkdir(parents=True)
    (normalized / "terse.pdf").write_bytes((REPO / "tests" / "fixtures" / "terse.pdf").read_bytes())
    build(MINI_HE / "outline.json", MINI_HE / "modules", tmp_path, ASSETS)
    (tmp_path / ".p2c" / "outline.json").write_text((MINI_HE / "outline.json").read_text())
    return tmp_path


def test_a_sound_course_violates_nothing(course_dir):
    assert check_course(course_dir) == []


def test_a_sound_hebrew_course_violates_nothing(course_dir_he):
    """Confirms check_course needs no language-specific changes: same invariants,
    same result, regardless of the course's language."""
    assert check_course(course_dir_he) == []


def test_a_missing_artifact_is_reported(course_dir):
    (course_dir / f"{MINI_BASENAME}.html").unlink()
    assert any(f"{MINI_BASENAME}.html" in p for p in check_course(course_dir))


def test_a_dropped_topic_is_caught(course_dir):
    md = course_dir / f"{MINI_BASENAME}.md"
    text = md.read_text()
    start = text.index("<!-- topic: thrashing -->")
    end = text.index("## Scheduling")
    md.write_text(text[:start] + text[end:])
    problems = check_course(course_dir)
    assert any("thrashing" in p for p in problems)


def test_a_topic_without_a_quiz_is_caught(course_dir):
    md = course_dir / f"{MINI_BASENAME}.md"
    text = md.read_text()
    head, _, tail = text.partition("```quiz")
    md.write_text(head + tail.partition("```")[2])
    assert any("quiz" in p for p in check_course(course_dir))


def test_a_jargon_term_with_no_glossary_entry_is_caught(course_dir):
    md = course_dir / f"{MINI_BASENAME}.md"
    md.write_text(md.read_text().replace("Working set: The pages", "Workingset: The pages"))
    assert any("Working set" in p for p in check_course(course_dir))


def test_a_placeholder_is_caught(course_dir):
    md = course_dir / f"{MINI_BASENAME}.md"
    md.write_text(md.read_text().replace("The TLB is that sticky note.", "TODO write this"))
    assert any("placeholder" in p.lower() for p in check_course(course_dir))


def test_an_external_request_in_the_html_is_caught(course_dir):
    html = course_dir / f"{MINI_BASENAME}.html"
    html.write_text(
        html.read_text().replace("</head>", '<script src="https://cdn.example.com/x.js"></script></head>')
    )
    assert any("network" in p.lower() or "external" in p.lower() for p in check_course(course_dir))


def test_a_leftover_template_placeholder_is_caught(course_dir):
    html = course_dir / f"{MINI_BASENAME}.html"
    html.write_text(html.read_text().replace("<h1", "{{CONTENT}}<h1", 1))
    assert any("{{CONTENT}}" in p for p in check_course(course_dir))


def test_a_toc_link_with_no_target_is_caught(course_dir):
    html = course_dir / f"{MINI_BASENAME}.html"
    html.write_text(html.read_text().replace('href="#thrashing"', 'href="#nowhere"'))
    assert any("nowhere" in p for p in check_course(course_dir))


def test_a_term_control_with_no_glossary_target_is_caught(course_dir):
    html = course_dir / f"{MINI_BASENAME}.html"
    html.write_text(html.read_text().replace('id="def-tlb"', 'id="def-tee-el-bee"'))
    assert any("def-tlb" in p for p in check_course(course_dir))


def test_the_quiz_count_must_survive_rendering(course_dir):
    html = course_dir / f"{MINI_BASENAME}.html"
    text = html.read_text()
    start = text.index('<details class="quiz"')
    end = text.index("</details>", start) + len("</details>")
    html.write_text(text[:start] + text[end:])
    assert any("quiz" in p for p in check_course(course_dir))


def test_the_pdf_is_only_required_when_asked(course_dir):
    assert check_course(course_dir, require_pdf=False) == []
    assert any(f"{MINI_BASENAME}.pdf" in p for p in check_course(course_dir, require_pdf=True))


def test_a_zero_page_pdf_is_caught(course_dir):
    (course_dir / f"{MINI_BASENAME}.pdf").write_bytes(make_pdf([]))
    assert any(f"{MINI_BASENAME}.pdf" in p for p in check_course(course_dir, require_pdf=True))


def test_a_real_pdf_satisfies_the_page_count_invariant(course_dir):
    (course_dir / f"{MINI_BASENAME}.pdf").write_bytes(make_pdf([["a"], ["b"]]))
    assert check_course(course_dir, require_pdf=True) == []


def test_a_course_with_a_diagram_is_not_falsely_flagged_as_reaching_the_network(tmp_path):
    modules = tmp_path / "modules"
    modules.mkdir()
    for name in ("01-virtual-memory.md", "02-scheduling.md"):
        modules.joinpath(name).write_text((MINI / "modules" / name).read_text())
    with modules.joinpath("02-scheduling.md").open("a") as handle:
        handle.write("\n```mermaid\nflowchart LR\n  A[Run] --> B[Queue]\n```\n")
    out = tmp_path / "out"
    normalized = out / ".p2c" / "normalized"
    normalized.mkdir(parents=True)
    (normalized / "terse.pdf").write_bytes(
        (REPO / "tests" / "fixtures" / "terse.pdf").read_bytes()
    )
    build(MINI / "outline.json", modules, out, ASSETS)
    (out / ".p2c" / "outline.json").write_text((MINI / "outline.json").read_text())
    assert check_course(out) == []


@pytest.mark.skipif(
    not os.environ.get("P2C_COURSE_DIR"), reason="set P2C_COURSE_DIR to grade a real run"
)
def test_a_real_run_is_sound():
    problems = check_course(Path(os.environ["P2C_COURSE_DIR"]), require_pdf=False)
    assert problems == [], "\n".join(problems)
