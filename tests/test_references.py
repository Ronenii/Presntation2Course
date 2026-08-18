from pathlib import Path

import pytest

from p2c.mdrender import HANDLED_KINDS
from p2c.outline import REQUIRED_TOPIC, SUBJECT_DOMAINS

REFS = Path(__file__).resolve().parents[1] / "references"


@pytest.mark.parametrize(
    "name",
    ["rubric.md", "style-guide.md", "quiz-format.md", "outline-schema.json",
     "agents/summarizer.md", "agents/researcher.md", "agents/course-writer.md",
     "agents/novice-simulator.md", "agents/rubric-auditor.md"],
)
def test_every_reference_file_exists_and_is_substantial(name):
    text = (REFS / name).read_text()
    assert len(text) > 500, name


def test_style_guide_fixes_the_topic_rhythm_and_the_analogy_rule():
    text = (REFS / "style-guide.md").read_text()
    for phrase in ["plain-language framing", "analogy", "technical", "visual",
                   "worked example", "quiz"]:
        assert phrase in text.lower(), phrase
    assert "before" in text.lower()
    assert "never invent" in text.lower() or "never fabricate" in text.lower()


def test_summarizer_prompt_states_the_outline_contract():
    text = (REFS / "agents" / "summarizer.md").read_text()
    assert "outline.json" in text
    assert "outline-schema.json" in text
    assert "20" in text  # pages are read in batches of 20
    for key in REQUIRED_TOPIC:
        assert key in text, key
    for domain in SUBJECT_DOMAINS:
        assert domain in text, domain
    assert "blank" in text.lower()
    assert "language" in text.lower()
    assert "kebab-case" in text.lower()


def test_researcher_prompt_states_the_unverified_rule():
    text = (REFS / "agents" / "researcher.md").read_text()
    assert "research/<topic-id>.md" in text
    assert "unverified: true" in text
    assert "never" in text.lower() and "invent" in text.lower()
    for section in ["definition", "why it matters", "analog", "worked example",
                    "misconception", "visualization", "sources"]:
        assert section in text.lower(), section


def test_course_writer_prompt_states_every_mechanical_requirement():
    text = (REFS / "agents" / "course-writer.md").read_text()
    assert "<!-- topic:" in text
    assert "```glossary" in text
    assert "```quiz" in text
    assert "```analogy" in text
    assert "```unverified" in text
    assert "###" in text
    assert "modules/" in text
    for kind in HANDLED_KINDS:
        if kind != "prereq":
            assert kind in text, kind
    assert "prereq" in text  # documented as build-owned, not writer-owned


def test_course_writer_prompt_states_the_language_and_jargon_rule():
    text = (REFS / "agents" / "course-writer.md").read_text()
    lowered = text.lower()
    assert "language" in lowered
    assert "original form" in lowered or "original-form" in lowered


def test_course_writer_prompt_states_the_mermaid_label_language_rule():
    text = (REFS / "agents" / "course-writer.md").read_text().lower()
    assert "mermaid" in text
    assert "label" in text or "node" in text


def test_course_writer_prompt_tells_writers_not_to_derive_their_own_filename():
    text = (REFS / "agents" / "course-writer.md").read_text().lower()
    assert "modules/" in text
    assert "do not derive" in text or "not derive" in text
    assert "orchestrator" in text


def test_reviewer_prompts_keep_their_own_findings_in_english():
    for name in ("novice-simulator.md", "rubric-auditor.md"):
        text = (REFS / "agents" / name).read_text().lower()
        assert "english" in text, name


def test_summarizer_documents_reusable_image():
    text = (REFS / "agents/summarizer.md").read_text()
    assert "reusable_image" in text


def test_rubric_notes_figure_and_animate_are_covered_by_existing_codes():
    text = (REFS / "rubric.md").read_text()
    assert "figure" in text
    assert "animate" in text


def test_course_writer_prompt_documents_the_animate_patterns():
    prose = (REFS / "agents" / "course-writer.md").read_text()
    assert "state-machine" in prose
    assert "pipeline" in prose


def test_quiz_format_documents_the_animate_patterns():
    prose = (REFS / "quiz-format.md").read_text()
    assert "state-machine" in prose
    assert "pipeline" in prose


def test_no_reference_doc_advertises_a_removed_pattern():
    """A documented pattern the parser rejects is worse than no documentation:
    the writer copies the example verbatim and the build fails. array-ops and
    path-trace are gone, so no author-facing file may still name them.
    """
    for path in (
        REFS / "agents" / "course-writer.md",
        REFS / "quiz-format.md",
        REFS / "rubric.md",
    ):
        prose = path.read_text()
        for dead in ("array-ops", "path-trace"):
            assert dead not in prose, f"{path.name} still documents {dead}"


def test_researcher_prompt_uses_the_strict_sources_grammar():
    prose = (REFS / "agents" / "researcher.md").read_text()
    assert "- Title: url" in prose or "Title: url" in prose
    assert "https://example.com/page" not in prose  # old em-dash example replaced
