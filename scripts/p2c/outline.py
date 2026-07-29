"""The summarizer's output contract.

Validated by hand rather than with jsonschema so the pipeline keeps a single runtime
dependency. tests/test_outline.py asserts this file and references/outline-schema.json
agree on every required key.
"""

import json
import re
from collections.abc import Iterator
from pathlib import Path

SUBJECT_DOMAINS = ("systems", "theory", "life-sciences", "other")
REQUIRED_TOP = ("title", "subject_domain", "source_decks", "modules")
REQUIRED_MODULE = ("id", "title", "prerequisites", "topics")
REQUIRED_TOPIC = ("id", "title", "slide_refs", "jargon", "diagrams", "gaps")
_SLIDE_REF = re.compile(r"^.+#\d+$")


class OutlineError(ValueError):
    """outline.json is missing, unparseable, or does not satisfy the contract."""


def _check_str(obj: dict, key: str, where: str, problems: list[str]) -> None:
    if not isinstance(obj.get(key), str) or not obj[key].strip():
        problems.append(f"{where}.{key} must be a non-empty string")


def _check_str_list(obj: dict, key: str, where: str, problems: list[str]) -> None:
    value = obj.get(key)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        problems.append(f"{where}.{key} must be a list of strings")


def validate_outline(obj: object) -> list[str]:
    problems: list[str] = []
    if not isinstance(obj, dict):
        return ["outline must be a JSON object"]
    for key in REQUIRED_TOP:
        if key not in obj:
            problems.append(f"outline is missing required key '{key}'")
    if isinstance(obj.get("title"), str) is False and "title" in obj:
        problems.append("outline.title must be a non-empty string")
    if "subject_domain" in obj and obj["subject_domain"] not in SUBJECT_DOMAINS:
        problems.append(
            f"outline.subject_domain must be one of {list(SUBJECT_DOMAINS)}, "
            f"got {obj['subject_domain']!r}"
        )
    if "source_decks" in obj:
        _check_str_list(obj, "source_decks", "outline", problems)

    modules = obj.get("modules")
    if not isinstance(modules, list):
        return problems
    if not modules:
        problems.append("outline.modules must contain at least one module")

    seen_modules: set[str] = set()
    seen_topics: set[str] = set()
    for mi, module in enumerate(modules):
        where = f"outline.modules[{mi}]"
        if not isinstance(module, dict):
            problems.append(f"{where} must be an object")
            continue
        for key in REQUIRED_MODULE:
            if key not in module:
                problems.append(f"{where} is missing required key '{key}'")
        for key in ("id", "title"):
            if key in module:
                _check_str(module, key, where, problems)
        if "prerequisites" in module:
            _check_str_list(module, "prerequisites", where, problems)
        mid = module.get("id")
        if isinstance(mid, str):
            if mid in seen_modules:
                problems.append(f"{where}: duplicate module id {mid!r}")
            seen_modules.add(mid)

        topics = module.get("topics")
        if not isinstance(topics, list):
            continue
        if not topics:
            problems.append(f"{where}.topics must contain at least one topic")
        for ti, topic in enumerate(topics):
            twhere = f"{where}.topics[{ti}]"
            if not isinstance(topic, dict):
                problems.append(f"{twhere} must be an object")
                continue
            for key in REQUIRED_TOPIC:
                if key not in topic:
                    problems.append(f"{twhere} is missing required key '{key}'")
            for key in ("id", "title"):
                if key in topic:
                    _check_str(topic, key, twhere, problems)
            for key in ("slide_refs", "jargon", "diagrams", "gaps"):
                if key in topic:
                    _check_str_list(topic, key, twhere, problems)
            refs = topic.get("slide_refs")
            if isinstance(refs, list):
                for ref in refs:
                    if isinstance(ref, str) and not _SLIDE_REF.match(ref):
                        problems.append(
                            f"{twhere}.slide_refs entry {ref!r} must look like 'deck.pdf#12'"
                        )
            tid = topic.get("id")
            if isinstance(tid, str):
                if tid in seen_topics:
                    problems.append(f"{twhere}: duplicate topic id {tid!r}")
                seen_topics.add(tid)
    return problems


def load_outline(path: Path) -> dict:
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise OutlineError(f"{path}: cannot be read ({exc})") from exc
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OutlineError(f"{path} is not valid JSON: {exc}") from exc
    problems = validate_outline(obj)
    if problems:
        raise OutlineError(f"{path} is invalid:\n  - " + "\n  - ".join(problems))
    return obj


def iter_topics(outline: dict) -> Iterator[tuple[dict, dict]]:
    for module in outline["modules"]:
        for topic in module["topics"]:
            yield module, topic


def topic_ids(outline: dict) -> list[str]:
    return [topic["id"] for _, topic in iter_topics(outline)]


def module_jargon(module: dict) -> set[str]:
    return {term for topic in module["topics"] for term in topic["jargon"]}


def all_jargon(outline: dict) -> set[str]:
    return {term for module in outline["modules"] for term in module_jargon(module)}


def planned_agent_count(outline: dict) -> int:
    """One researcher per topic, one writer per module, two reviewers."""
    return len(topic_ids(outline)) + len(outline["modules"]) + 2
