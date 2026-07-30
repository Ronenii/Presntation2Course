import json

import pytest

from p2c.review import (
    MAX_PASSES,
    REVIEW_CODES,
    REVIEWERS,
    ReviewError,
    finding_key,
    findings_from_review,
    load_review,
    main,
    new_blocking,
    oscillating,
    render_known_issues,
    should_continue,
    validate_review,
)
from p2c.validate import Finding


def review(**overrides):
    base = {
        "reviewer": "novice-simulator",
        "pass": 1,
        "findings": [
            {
                "code": "jargon_undefined",
                "message": "'MESI' is used in Cache coherence and never defined",
                "module": "m-cache",
                "topic": "coherence",
                "evidence": "the MESI protocol keeps caches consistent",
            },
            {
                "code": "verbosity",
                "message": "The scheduling topic repeats itself",
                "module": "m-sched",
                "topic": "round-robin",
                "evidence": "paragraphs 2 and 4",
            },
        ],
    }
    base.update(overrides)
    return base


def test_the_contract_covers_every_blocking_finding_the_design_lists():
    for code in (
        "jargon_undefined",
        "topic_without_quiz",
        "quiz_needs_outside_knowledge",
        "unsupported_claim",
        "topic_missing",
        "analogy_misleading",
        "missing_background",
    ):
        route, blocking = REVIEW_CODES[code]
        assert blocking is True
        assert route in {"writer", "researcher", "summarizer", "build"}


def test_noted_codes_never_block():
    for code in ("verbosity", "style", "missing_visual", "other"):
        assert REVIEW_CODES[code][1] is False


def test_routing_matches_the_design_table():
    assert REVIEW_CODES["missing_background"][0] == "researcher"
    assert REVIEW_CODES["unsupported_claim"][0] == "researcher"
    assert REVIEW_CODES["analogy_misleading"][0] == "writer"
    assert REVIEW_CODES["quiz_needs_outside_knowledge"][0] == "writer"
    assert REVIEW_CODES["jargon_undefined"][0] == "writer"
    assert REVIEW_CODES["topic_missing"][0] == "summarizer"


def test_a_well_formed_review_validates():
    assert validate_review(review()) == []


def test_max_passes_is_three_and_reviewers_are_the_two_from_the_design():
    assert MAX_PASSES == 3
    assert REVIEWERS == ("novice-simulator", "rubric-auditor")


@pytest.mark.parametrize(
    "obj,message",
    [
        ([], "review must be a JSON object"),
        ({"pass": 1, "findings": []}, "missing required key 'reviewer'"),
        (review(reviewer="nobody"), "unknown reviewer"),
        (review(**{"pass": 0}), "pass must be between 1 and 3"),
        (review(**{"pass": 4}), "pass must be between 1 and 3"),
        (review(findings={}), "findings must be a list"),
        (review(findings=[{"message": "m"}]), "findings[0] is missing required key 'code'"),
        (review(findings=[{"code": "made_up", "message": "m"}]), "unknown finding code"),
        (review(findings=[{"code": "verbosity", "message": ""}]), "message must be a non-empty string"),
    ],
)
def test_validate_review_rejects_bad_input(obj, message):
    problems = validate_review(obj)
    assert any(message in p for p in problems), problems


def test_load_review_reads_and_validates(tmp_path):
    path = tmp_path / "pass-1.json"
    path.write_text(json.dumps(review()))
    assert load_review(path)["pass"] == 1


def test_load_review_raises_on_invalid_content(tmp_path):
    path = tmp_path / "pass-1.json"
    path.write_text(json.dumps({"reviewer": "novice-simulator"}))
    with pytest.raises(ReviewError, match="findings"):
        load_review(path)


def test_load_review_raises_on_bad_json(tmp_path):
    path = tmp_path / "pass-1.json"
    path.write_text("{oops")
    with pytest.raises(ReviewError, match="not valid JSON"):
        load_review(path)


def test_findings_carry_route_and_blocking_from_the_contract():
    findings = findings_from_review(review())
    assert isinstance(findings[0], Finding)
    assert findings[0].blocking is True
    assert findings[0].route == "writer"
    assert findings[0].module == "m-cache"
    assert findings[0].topic == "coherence"
    assert findings[1].blocking is False


def test_a_reviewer_supplied_route_is_ignored():
    obj = review(findings=[{"code": "unsupported_claim", "message": "m", "route": "build"}])
    assert findings_from_review(obj)[0].route == "researcher"


def test_finding_key_ignores_wording_but_not_identity():
    a = Finding(code="jargon_undefined", message="'MESI' is never defined", module="m", topic="t")
    b = Finding(code="jargon_undefined", message="  'MESI' IS never   defined ", module="m", topic="t")
    c = Finding(code="jargon_undefined", message="'MOESI' is never defined", module="m", topic="t")
    assert finding_key(a) == finding_key(b)
    assert finding_key(a) != finding_key(c)


def test_new_blocking_ignores_noted_and_already_seen_findings():
    findings = findings_from_review(review())
    keys = {finding_key(f) for f in findings}
    assert [f.code for f in new_blocking(findings, set())] == ["jargon_undefined"]
    assert new_blocking(findings, keys) == []


def test_oscillating_flags_a_finding_that_came_back_after_being_fixed():
    findings = findings_from_review(review())
    fixed = {finding_key(findings[0])}
    assert [f.code for f in oscillating(findings, fixed)] == ["jargon_undefined"]
    assert oscillating(findings, set()) == []


@pytest.mark.parametrize(
    "pass_number,new_count,expected",
    [
        (1, 2, True),    # blocking findings remain and passes are left
        (1, 0, False),   # early exit: nothing new is blocking
        (2, 1, True),
        (3, 5, False),   # hard cap reached
        (4, 5, False),
    ],
)
def test_should_continue_enforces_both_guards(pass_number, new_count, expected):
    assert should_continue(pass_number, new_count) is expected


def test_known_issues_lists_only_blocking_findings_with_routes():
    findings = findings_from_review(review())
    text = render_known_issues(findings, course_title="Operating Systems")
    assert text.startswith("# Known issues — Operating Systems")
    assert "MESI" in text
    assert "m-cache" in text and "coherence" in text
    assert "repeats itself" not in text
    assert "three review passes" in text


def test_known_issues_is_empty_when_nothing_blocks():
    noted = [Finding(code="verbosity", message="wordy", blocking=False, route="writer")]
    assert render_known_issues(noted, course_title="X") == ""


def test_main_check_subcommand_on_valid_review(tmp_path, capsys):
    path = tmp_path / "pass-1.json"
    path.write_text(json.dumps(review()))
    exit_code = main(["check", str(path)])
    assert exit_code == 0
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["reviewer"] == "novice-simulator"
    assert output["pass"] == 1
    assert output["findings"] == 2


def test_main_known_issues_subcommand(tmp_path, capsys):
    # Case 1: with blocking findings
    review_path = tmp_path / "pass-1.json"
    review_path.write_text(json.dumps(review()))
    out_path = tmp_path / "KNOWN-ISSUES.md"
    exit_code = main(["known-issues", str(review_path), "--title", "Test Course", "--out", str(out_path)])
    assert exit_code == 0
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["written"] == str(out_path)
    assert output["blocking"] == 1  # only jargon_undefined is blocking
    assert out_path.exists()
    content = out_path.read_text()
    assert "# Known issues — Test Course" in content
    assert "jargon_undefined" in content

    # Case 2: with no blocking findings
    noted_review = review(findings=[
        {"code": "verbosity", "message": "wordy", "module": "m", "topic": "t"}
    ])
    review_path2 = tmp_path / "pass-2.json"
    review_path2.write_text(json.dumps(noted_review))
    out_path2 = tmp_path / "KNOWN-ISSUES-empty.md"
    exit_code = main(["known-issues", str(review_path2), "--title", "Empty", "--out", str(out_path2)])
    assert exit_code == 0
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["written"] is None
    assert output["blocking"] == 0
    assert not out_path2.exists()
