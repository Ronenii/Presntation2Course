import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILL = (REPO / "SKILL.md").read_text()


def test_front_matter_names_the_skill_and_says_when_to_use_it():
    assert SKILL.startswith("---\n")
    front = SKILL.split("---", 2)[1]
    assert re.search(r"^name:\s*presentation2course\s*$", front, re.MULTILINE)
    description = re.search(r"^description:\s*(.+)$", front, re.MULTILINE)
    assert description
    text = description.group(1).lower()
    assert "deck" in text or "slide" in text
    assert "course" in text


def test_every_phase_is_documented_in_order():
    positions = [SKILL.index(f"Phase {n}") for n in range(6)]
    assert positions == sorted(positions)
    for role in ("summarizer", "researcher", "course-writer", "novice-simulator",
                 "rubric-auditor"):
        assert f"references/agents/{role}.md" in SKILL


def test_every_script_is_invoked_with_its_documented_exit_codes():
    for fragment in ("scripts/normalize", "scripts/build", "scripts/export-pdf"):
        assert fragment in SKILL
    for code in ("exit 3", "exit 4", "exit 5", "exit 6"):
        assert code in SKILL


def test_the_run_layout_matches_the_design():
    for artifact in (
        "course.html", "course.pdf", "course.md", "KNOWN-ISSUES.md",
        ".p2c/normalized", ".p2c/outline.json", ".p2c/research/",
        ".p2c/modules/", ".p2c/review/",
    ):
        assert artifact in SKILL, artifact


def test_the_loop_guards_are_all_stated():
    lowered = SKILL.lower()
    assert "three passes" in lowered or "3 passes" in lowered
    assert "no new blocking" in lowered
    assert "oscillation" in lowered
    assert "known-issues.md" in lowered


def test_the_zero_questions_and_no_fabrication_rules_are_stated():
    lowered = SKILL.lower()
    assert "no questions" in lowered or "never ask" in lowered
    assert "fabricat" in lowered or "invent" in lowered


def test_export_pdf_runs_once_after_the_loop():
    export = SKILL.index("scripts/export-pdf")
    loop = SKILL.index("Phase 5")
    assert export > loop
    assert "once" in SKILL[export - 400 : export + 400].lower()


def test_the_planned_agent_count_is_reported():
    assert "planned_agent_count" in SKILL


def test_parallel_fan_out_is_explicit():
    lowered = SKILL.lower()
    assert "one agent per topic" in lowered
    assert "one agent per module" in lowered
    assert "parallel" in lowered
