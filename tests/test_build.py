import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from p2c.build import build, main
from p2c.theme import TEMPLATE_PLACEHOLDERS

REPO = Path(__file__).resolve().parents[1]
MINI = REPO / "tests" / "fixtures" / "mini-course"
ASSETS = REPO / "assets"
GOLDEN = REPO / "tests" / "golden" / "course.html"


@pytest.fixture
def built(tmp_path):
    return build(MINI / "outline.json", MINI / "modules", tmp_path, ASSETS)


def test_build_writes_all_three_artifacts(built, tmp_path):
    assert built.course_md == tmp_path / "course.md"
    assert built.course_html == tmp_path / "course.html"
    assert built.findings_path == tmp_path / ".p2c" / "review" / "build-findings.json"
    for path in (built.course_md, built.course_html, built.findings_path):
        assert path.is_file()


def test_the_mini_course_builds_clean(built):
    assert [f.code for f in built.findings] == []
    assert json.loads(built.findings_path.read_text()) == []


def test_theme_comes_from_subject_domain(built):
    assert built.theme == "slate"
    html = built.course_html.read_text()
    assert 'data-course-theme="slate"' in html
    assert "--mermaid-primary: #e4ebf7;" in html


def test_theme_can_be_overridden(tmp_path):
    result = build(MINI / "outline.json", MINI / "modules", tmp_path, ASSETS, theme="parchment")
    assert result.theme == "parchment"
    assert "ui-serif" in result.course_html.read_text()


def test_no_placeholder_survives_in_the_html(built):
    html = built.course_html.read_text()
    for placeholder in TEMPLATE_PLACEHOLDERS:
        assert placeholder not in html


def test_the_html_is_self_contained(built):
    html = built.course_html.read_text()
    assert "<style>" in html
    assert "https://" not in html
    assert "http://" not in html
    assert "@import" not in html


def test_mermaid_is_not_inlined_when_the_course_has_no_diagrams(built):
    html = built.course_html.read_text()
    assert "__esbuild_esm_mermaid_nm" not in html
    assert len(html) < 200_000


def test_mermaid_is_inlined_once_when_a_diagram_is_present(tmp_path):
    modules = tmp_path / "modules"
    modules.mkdir()
    for name in ("01-virtual-memory.md", "02-scheduling.md"):
        modules.joinpath(name).write_text((MINI / "modules" / name).read_text())
    with modules.joinpath("02-scheduling.md").open("a") as handle:
        handle.write("\n```mermaid\nflowchart LR\n  A[Run] --> B[Queue]\n```\n")
    result = build(MINI / "outline.json", modules, tmp_path / "out", ASSETS)
    html = result.course_html.read_text()
    assert html.count("__esbuild_esm_mermaid_nm") >= 1
    assert html.count('<div class="mermaid">') == 1
    assert [f.code for f in result.findings] == []


def test_course_md_is_the_source_of_truth_and_reproducible(built, tmp_path):
    first = built.course_md.read_text()
    again = build(MINI / "outline.json", MINI / "modules", tmp_path / "second", ASSETS)
    assert again.course_md.read_text() == first
    assert again.course_html.read_text() == built.course_html.read_text()


def test_the_shipped_html_declares_language_and_direction(built):
    html = built.course_html.read_text()
    assert 'lang="en"' in html
    assert 'dir="ltr"' in html


def test_an_rtl_language_gets_dir_rtl_and_its_own_lang(tmp_path):
    outline = json.loads((MINI / "outline.json").read_text())
    outline["language"] = {"name": "Hebrew", "code": "he"}
    outline_path = tmp_path / "outline.json"
    outline_path.write_text(json.dumps(outline))
    result = build(outline_path, MINI / "modules", tmp_path / "out", ASSETS)
    html = result.course_html.read_text()
    assert 'lang="he"' in html
    assert 'dir="rtl"' in html


def test_content_reaches_the_html_with_structure(built):
    html = built.course_html.read_text()
    assert "<h1 id=\"operating-systems-foundations\">" in html
    assert '<h2 id="virtual-memory">' in html
    assert '<h3 id="what-a-tlb-caches">' in html
    assert 'class="callout callout--analogy"' in html
    assert 'class="callout callout--prereq"' in html
    assert html.count('class="quiz"') == 3
    assert '<dt id="def-tlb">TLB</dt>' in html
    assert 'aria-controls="def-tlb"' in html
    assert '<a href="#thrashing">' in html


def test_blocking_findings_are_reported_and_still_render(tmp_path):
    modules = tmp_path / "modules"
    modules.mkdir()
    modules.joinpath("01-virtual-memory.md").write_text(
        "<!-- topic: tlb -->\n### What a TLB caches\n\nNo quiz, no glossary.\n"
    )
    modules.joinpath("02-scheduling.md").write_text(
        (MINI / "modules" / "02-scheduling.md").read_text()
    )
    result = build(MINI / "outline.json", modules, tmp_path / "out", ASSETS)
    codes = {f.code for f in result.findings}
    assert "topic_without_quiz" in codes
    assert "topic_missing" in codes
    assert "jargon_without_glossary" in codes
    assert result.course_html.is_file()  # a defective course still renders for review
    recorded = json.loads(result.findings_path.read_text())
    assert {f["code"] for f in recorded} == codes
    assert {f["route"] for f in recorded} <= {"writer", "researcher", "summarizer", "build"}


def test_matches_the_golden_snapshot(built):
    if os.environ.get("P2C_UPDATE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(built.course_html.read_text())
    assert built.course_html.read_text() == GOLDEN.read_text(), (
        "course.html changed; re-run with P2C_UPDATE_GOLDEN=1 and review the diff"
    )


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "build"), *map(str, args)],
        capture_output=True,
        text=True,
    )


def test_cli_exit_0_and_json_summary(tmp_path):
    proc = _run_cli(
        "--outline", MINI / "outline.json",
        "--modules", MINI / "modules",
        "--out", tmp_path,
        "--assets", ASSETS,
    )
    assert proc.returncode == 0, proc.stderr
    summary = json.loads(proc.stdout)
    assert summary["theme"] == "slate"
    assert summary["quiz_count"] == 3
    assert summary["topics"] == 3
    assert summary["blocking"] == []
    assert summary["uses_mermaid"] is False
    assert summary["course_html"].endswith("course.html")


def test_cli_exit_3_on_blocking_findings(tmp_path):
    modules = tmp_path / "modules"
    modules.mkdir()
    modules.joinpath("01-virtual-memory.md").write_text("<!-- topic: tlb -->\n### T\n\nBare.\n")
    modules.joinpath("02-scheduling.md").write_text(
        (MINI / "modules" / "02-scheduling.md").read_text()
    )
    proc = _run_cli(
        "--outline", MINI / "outline.json", "--modules", modules,
        "--out", tmp_path / "out", "--assets", ASSETS,
    )
    assert proc.returncode == 3
    assert json.loads(proc.stdout)["blocking"]


def test_cli_exit_1_on_a_missing_module_file(tmp_path):
    modules = tmp_path / "modules"
    modules.mkdir()
    proc = _run_cli(
        "--outline", MINI / "outline.json", "--modules", modules,
        "--out", tmp_path / "out", "--assets", ASSETS,
    )
    assert proc.returncode == 1
    assert "01-virtual-memory.md" in proc.stderr


def test_cli_exit_2_without_arguments():
    assert _run_cli().returncode == 2
