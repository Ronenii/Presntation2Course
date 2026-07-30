"""Concatenate module files into course.md.

The module heading and the prerequisite callout are emitted here, not by the writer, so
heading levels are structurally identical across modules and cannot drift.
"""

from dataclasses import dataclass, field
from pathlib import Path

from p2c.text import slugify
from p2c.theme import theme_for

REQUIRED_KEYS = ("title", "subject_domain", "theme")


class AssembleError(Exception):
    """A module file is missing or empty, or front matter is malformed."""


@dataclass
class FrontMatter:
    title: str
    subject_domain: str
    theme: str
    source_decks: list[str] = field(default_factory=list)


def render_front_matter(fm: FrontMatter) -> str:
    for name, value in (("title", fm.title), ("subject_domain", fm.subject_domain),
                        ("theme", fm.theme)):
        if "\n" in value:
            raise AssembleError(f"front matter {name} may not contain a newline")
    lines = [
        "---",
        f"title: {fm.title}",
        f"subject_domain: {fm.subject_domain}",
        f"theme: {fm.theme}",
        "source_decks:",
    ]
    lines.extend(f"  - {deck}" for deck in fm.source_decks)
    lines.append("---")
    return "\n".join(lines) + "\n"


def parse_front_matter(text: str) -> tuple[FrontMatter, str]:
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise AssembleError("course.md must start with a '---' front matter block")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise AssembleError("course.md front matter block is not closed")

    values: dict[str, str] = {}
    decks: list[str] = []
    current_list: str | None = None
    for line in lines[1:end]:
        if not line.strip():
            continue
        if line.startswith("  - "):
            if current_list != "source_decks":
                raise AssembleError(f"unparseable front matter line: {line!r}")
            decks.append(line[4:].strip())
            continue
        if ":" not in line:
            raise AssembleError(f"unparseable front matter line: {line!r}")
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        current_list = key if not value else None
        if value:
            values[key] = value
    for key in REQUIRED_KEYS:
        if key not in values:
            raise AssembleError(f"missing front matter key {key!r}")

    fm = FrontMatter(
        title=values["title"],
        subject_domain=values["subject_domain"],
        theme=values["theme"],
        source_decks=decks,
    )
    return fm, "\n".join(lines[end + 1 :])


def module_filename(index: int, module: dict) -> str:
    """1-based index so the writer and the build agree without extra bookkeeping."""
    return f"{index:02d}-{slugify(module['title'])}.md"


def assemble(outline: dict, modules_dir: Path) -> str:
    modules_dir = Path(modules_dir)
    fm = FrontMatter(
        title=outline["title"],
        subject_domain=outline["subject_domain"],
        theme=theme_for(outline["subject_domain"]),
        source_decks=list(outline.get("source_decks", [])),
    )
    parts = [render_front_matter(fm), "", f"# {outline['title']}", ""]
    for index, module in enumerate(outline["modules"], start=1):
        path = modules_dir / module_filename(index, module)
        if not path.is_file():
            raise AssembleError(f"module file not written: {path}")
        body = path.read_text(encoding="utf-8").strip()
        if not body:
            raise AssembleError(f"module file {path.name} is empty")
        parts.extend([f"## {module['title']}", ""])
        if module.get("prerequisites"):
            parts.append("```prereq")
            parts.extend(f"- {item}" for item in module["prerequisites"])
            parts.extend(["```", ""])
        parts.extend([body, ""])
    return "\n".join(parts).rstrip("\n") + "\n"
