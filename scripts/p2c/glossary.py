"""Glossary blocks, in-prose term injection, and the appendix.

Terms are injected as tokens, not as HTML, so a definition's own words can never be
re-injected into itself and headings stay clean.
"""

import html
import re
from dataclasses import dataclass, field

from p2c.text import slugify

TERM_TOKEN = "P2CTERM{}ENDTERM"
_ENTRY = re.compile(r"^(?P<term>[^:]*):\s*(?P<definition>.*)$")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
_COMMENT = re.compile(r"^\s*<!--")


class GlossaryError(ValueError):
    """A glossary block that does not satisfy the grammar."""


def parse_glossary_block(body: str) -> dict[str, str]:
    terms: dict[str, str] = {}
    last: str | None = None
    for raw in body.split("\n"):
        if not raw.strip():
            continue
        if raw[:1].isspace():
            if last is None:
                raise GlossaryError("continuation line before any term")
            terms[last] = f"{terms[last]} {raw.strip()}".strip()
            continue
        entry = _ENTRY.match(raw.strip())
        if not entry:
            raise GlossaryError(f"expected 'term: definition', got {raw.strip()!r}")
        term = entry.group("term").strip()
        if not term:
            raise GlossaryError("glossary term is empty")
        if term in terms:
            raise GlossaryError(f"duplicate term {term!r} in one glossary block")
        terms[term] = entry.group("definition").strip()
        last = term
    if not terms:
        raise GlossaryError("glossary block is empty")
    for term, definition in terms.items():
        if not definition:
            raise GlossaryError(f"definition for {term!r} is empty")
    return terms


def merge_glossaries(blocks: list[dict[str, str]]) -> dict[str, str]:
    """Course-wide union. Case-insensitive; the first definition seen wins."""
    merged: dict[str, str] = {}
    seen: set[str] = set()
    for block in blocks:
        for term, definition in block.items():
            key = term.lower()
            if key in seen:
                continue
            seen.add(key)
            merged[term] = definition
    return merged


def term_ids(terms: dict[str, str]) -> dict[str, str]:
    return {term.lower(): f"def-{slugify(term)}" for term in terms}


@dataclass
class TermInjector:
    """Wraps the first occurrence of each known term, per call, in a reveal control."""

    terms: dict[str, str]
    ids: dict[str, str]
    replacements: dict[str, str] = field(default_factory=dict)

    def _patterns(self) -> list[tuple[str, re.Pattern[str]]]:
        # Longest first so "page table walk" wins over "page table".
        ordered = sorted(self.terms, key=lambda t: len(t), reverse=True)
        return [
            (term, re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE))
            for term in ordered
        ]

    def _control(self, shown: str, term: str) -> str:
        token = TERM_TOKEN.format(len(self.replacements))
        def_id = self.ids[term.lower()]
        definition = html.escape(self.terms[term])
        self.replacements[token] = (
            '<span class="term-wrap">'
            f'<button type="button" class="term" aria-expanded="false" '
            f'aria-controls="{def_id}">{html.escape(shown)}</button>'
            f'<span class="term__def" id="{def_id}" hidden>{definition}</span>'
            "</span>"
        )
        return token

    def inject(self, md: str) -> str:
        """Inject into one topic's body. Headings and comment markers are skipped."""
        patterns = self._patterns()
        used: set[str] = set()
        lines = md.split("\n")
        for i, line in enumerate(lines):
            if _HEADING.match(line) or _COMMENT.match(line):
                continue
            for term, pattern in patterns:
                if term.lower() in used:
                    continue
                match = pattern.search(lines[i])
                if not match:
                    continue
                token = self._control(match.group(0), term)
                lines[i] = lines[i][: match.start()] + token + lines[i][match.end() :]
                used.add(term.lower())
        return "\n".join(lines)


def glossary_html(terms: dict[str, str], ids: dict[str, str]) -> str:
    rows = ['<dl class="glossary">']
    for term in sorted(terms, key=str.lower):
        rows.append(f'<dt id="{ids[term.lower()]}">{html.escape(term)}</dt>')
        rows.append(f"<dd>{html.escape(terms[term])}</dd>")
    rows.append("</dl>")
    return "\n".join(rows)
