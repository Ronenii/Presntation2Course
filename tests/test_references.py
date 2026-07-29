from pathlib import Path

import pytest

from p2c.mdrender import HANDLED_KINDS
from p2c.outline import REQUIRED_TOPIC, SUBJECT_DOMAINS

REFS = Path(__file__).resolve().parents[1] / "references"


# Task 17 adds rubric.md and the two reviewer prompts to this list when it writes them.
@pytest.mark.parametrize(
    "name",
    ["style-guide.md", "quiz-format.md", "outline-schema.json",
     "agents/summarizer.md", "agents/researcher.md", "agents/course-writer.md"],
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
