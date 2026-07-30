import json
from pathlib import Path

import pytest

from p2c.outline import (
    REQUIRED_MODULE,
    REQUIRED_TOP,
    REQUIRED_TOPIC,
    OutlineError,
    all_jargon,
    iter_topics,
    load_outline,
    module_jargon,
    planned_agent_count,
    topic_ids,
    validate_outline,
)

REPO = Path(__file__).resolve().parents[1]


def outline(**overrides):
    base = {
        "title": "Operating Systems",
        "subject_domain": "systems",
        "language": {"name": "English", "code": "en"},
        "source_decks": ["week1.pdf"],
        "modules": [
            {
                "id": "m-memory",
                "title": "Memory",
                "prerequisites": ["Binary arithmetic"],
                "topics": [
                    {
                        "id": "tlb",
                        "title": "The TLB",
                        "slide_refs": ["week1.pdf#12"],
                        "jargon": ["TLB", "Page table"],
                        "diagrams": ["A box diagram of address translation"],
                        "gaps": ["Why translation needs caching at all"],
                    },
                    {
                        "id": "thrashing",
                        "title": "Thrashing",
                        "slide_refs": ["week1.pdf#20"],
                        "jargon": ["Working set"],
                        "diagrams": [],
                        "gaps": [],
                    },
                ],
            }
        ],
    }
    base.update(overrides)
    return base


def test_a_well_formed_outline_validates():
    assert validate_outline(outline()) == []


def test_reports_every_missing_top_level_key():
    problems = validate_outline({})
    assert len(problems) == len(REQUIRED_TOP)
    for key in REQUIRED_TOP:
        assert any(key in p for p in problems)


def test_rejects_an_unknown_subject_domain():
    problems = validate_outline(outline(subject_domain="astrology"))
    assert any("subject_domain" in p and "astrology" in p for p in problems)


def test_rejects_a_non_object():
    assert validate_outline([]) == ["outline must be a JSON object"]


def test_rejects_zero_modules_and_zero_topics():
    assert any("at least one module" in p for p in validate_outline(outline(modules=[])))
    empty = outline()
    empty["modules"][0]["topics"] = []
    assert any("at least one topic" in p for p in validate_outline(empty))


def test_reports_missing_module_and_topic_keys_with_a_path():
    broken = outline()
    del broken["modules"][0]["prerequisites"]
    del broken["modules"][0]["topics"][0]["gaps"]
    problems = validate_outline(broken)
    assert any("modules[0]" in p and "prerequisites" in p for p in problems)
    assert any("modules[0].topics[0]" in p and "gaps" in p for p in problems)


def test_rejects_wrong_types():
    broken = outline()
    broken["modules"][0]["topics"][0]["jargon"] = "TLB"
    broken["modules"][0]["topics"][0]["title"] = 7
    problems = validate_outline(broken)
    assert any("jargon" in p and "list of strings" in p for p in problems)
    assert any("title" in p and "string" in p for p in problems)


def test_rejects_duplicate_ids():
    dupes = outline()
    dupes["modules"][0]["topics"][1]["id"] = "tlb"
    assert any("duplicate topic id 'tlb'" in p for p in validate_outline(dupes))
    two = outline()
    two["modules"].append(dict(two["modules"][0]))
    assert any("duplicate module id 'm-memory'" in p for p in validate_outline(two))


def test_rejects_a_malformed_slide_ref():
    broken = outline()
    broken["modules"][0]["topics"][0]["slide_refs"] = ["week1.pdf page 12"]
    assert any("slide_refs" in p and "deck.pdf#12" in p for p in validate_outline(broken))


def test_rejects_a_wrong_typed_modules_field():
    problems = validate_outline(outline(modules="not a list"))
    assert any("modules" in p and "list" in p for p in problems)


def test_rejects_a_wrong_typed_topics_field():
    broken = outline()
    broken["modules"][0]["topics"] = "not a list"
    problems = validate_outline(broken)
    assert any("topics" in p and "list" in p for p in problems)


def test_rejects_a_blank_top_level_title():
    problems = validate_outline(outline(title="   "))
    assert any("title" in p for p in problems)


def test_a_hebrew_language_outline_validates():
    assert validate_outline(outline(language={"name": "Hebrew", "code": "he"})) == []


def test_rejects_a_non_object_language():
    problems = validate_outline(outline(language="Hebrew"))
    assert any("outline.language must be an object" in p for p in problems)


def test_rejects_a_language_missing_name_or_code():
    problems = validate_outline(outline(language={"name": "Hebrew"}))
    assert any("outline.language" in p and "code" in p for p in problems)
    problems = validate_outline(outline(language={"code": "he"}))
    assert any("outline.language" in p and "name" in p for p in problems)


def test_rejects_an_empty_language_code():
    problems = validate_outline(outline(language={"name": "Hebrew", "code": "  "}))
    assert any("outline.language.code" in p for p in problems)


def test_helpers_walk_the_structure():
    o = outline()
    assert topic_ids(o) == ["tlb", "thrashing"]
    assert [t["id"] for _, t in iter_topics(o)] == ["tlb", "thrashing"]
    assert module_jargon(o["modules"][0]) == {"TLB", "Page table", "Working set"}
    assert all_jargon(o) == {"TLB", "Page table", "Working set"}


def test_planned_agent_count_is_topics_plus_modules_plus_reviewers():
    assert planned_agent_count(outline()) == 2 + 1 + 2


def test_load_outline_raises_with_every_problem(tmp_path):
    path = tmp_path / "outline.json"
    path.write_text(json.dumps({"title": "x"}))
    with pytest.raises(OutlineError) as exc:
        load_outline(path)
    assert "subject_domain" in str(exc.value)
    assert "modules" in str(exc.value)


def test_load_outline_reports_invalid_json(tmp_path):
    path = tmp_path / "outline.json"
    path.write_text("{not json")
    with pytest.raises(OutlineError, match="is not valid JSON"):
        load_outline(path)


def test_load_outline_accepts_the_good_case(tmp_path):
    path = tmp_path / "outline.json"
    path.write_text(json.dumps(outline()))
    assert load_outline(path)["title"] == "Operating Systems"


def test_published_schema_matches_the_validator():
    schema = json.loads((REPO / "references" / "outline-schema.json").read_text())
    topic = schema["$defs"]["topic"]
    module = schema["$defs"]["module"]
    assert set(schema["required"]) == set(REQUIRED_TOP)
    assert set(module["required"]) == set(REQUIRED_MODULE)
    assert set(topic["required"]) == set(REQUIRED_TOPIC)
