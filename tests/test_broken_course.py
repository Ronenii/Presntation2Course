import json
from pathlib import Path

from p2c.build import build
from p2c.review import missed_expected

REPO = Path(__file__).resolve().parents[1]
BROKEN = REPO / "tests" / "broken-course"
ASSETS = REPO / "assets"
EXPECTED = json.loads((BROKEN / "expected-findings.json").read_text())


def test_the_broken_course_passes_every_mechanical_validation(tmp_path):
    """If the build caught these defects, the fixture would not test the reviewer."""
    result = build(BROKEN / "outline.json", BROKEN / "modules", tmp_path, ASSETS)
    assert [f.code for f in result.findings] == []
    assert result.course_html.is_file()


def test_the_fixture_really_contains_the_two_defects():
    body = (BROKEN / "modules" / "01-cache-coherence.md").read_text()
    outline = json.loads((BROKEN / "outline.json").read_text())
    declared = {t.lower() for m in outline["modules"] for t in m["topics"][0]["jargon"]}
    # Defect 1: MESI is used in prose, is not declared jargon, and has no glossary entry.
    assert "MESI" in body
    assert "mesi" not in declared
    assert "MESI:" not in body
    # Defect 2: the quiz answer appears nowhere in the prose.
    assert "four states" not in body.split("```quiz")[0]


def test_expected_findings_names_both_defects():
    codes = {entry["code"] for entry in EXPECTED["must_catch"]}
    assert codes == {"jargon_undefined", "quiz_needs_outside_knowledge"}


def _review(findings):
    return {"reviewer": "novice-simulator", "pass": 1, "findings": findings}


def test_a_reviewer_that_catches_both_defects_passes():
    review = _review([
        {"code": "jargon_undefined", "message": "MESI is used and never defined",
         "module": "m-cache", "topic": "coherence"},
        {"code": "quiz_needs_outside_knowledge",
         "message": "The quiz asks how many states MESI has; the course never says four",
         "module": "m-cache", "topic": "coherence"},
    ])
    assert missed_expected(review, EXPECTED) == []


def test_a_reviewer_that_misses_a_defect_is_reported():
    review = _review([
        {"code": "jargon_undefined", "message": "MESI is used and never defined"},
    ])
    missed = missed_expected(review, EXPECTED)
    assert len(missed) == 1
    assert "quiz_needs_outside_knowledge" in missed[0]


def test_the_right_code_with_the_wrong_subject_does_not_count():
    review = _review([
        {"code": "jargon_undefined", "message": "'working set' is never defined"},
        {"code": "quiz_needs_outside_knowledge", "message": "the second quiz is unfair"},
    ])
    assert len(missed_expected(review, EXPECTED)) == 2


def test_evidence_counts_towards_matching():
    review = _review([
        {"code": "jargon_undefined", "message": "a term is never defined",
         "evidence": "the MESI protocol keeps caches consistent"},
        {"code": "quiz_needs_outside_knowledge", "message": "unanswerable",
         "evidence": "asks for the number of states; four is never stated"},
    ])
    assert missed_expected(review, EXPECTED) == []
