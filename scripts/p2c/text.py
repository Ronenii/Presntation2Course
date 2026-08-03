"""Slug and anchor generation. Shared by every id the course emits."""

import re
import unicodedata

from unidecode import unidecode

_NON_WORD = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """Lowercase ASCII slug. Never empty — falls back to 'section'."""
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    slug = _NON_WORD.sub("-", ascii_only.lower()).strip("-")
    return slug or "section"


def slugify_transliterated(text: str) -> str:
    """Like slugify(), but transliterates non-Latin scripts (Hebrew, Arabic,
    Cyrillic, ...) to ASCII first instead of discarding them — for filenames a
    person needs to recognize, where 'section' for every non-Latin course title
    is useless. Anchors don't need this: slugify() alone is fine there, since an
    anchor only needs to be a valid, unique href target, not a readable name.
    Still falls back to 'section' (via slugify()) if transliteration itself
    yields nothing sluggable, e.g. a title that is only emoji or symbols.
    """
    return slugify(unidecode(text))


class AnchorAllocator:
    """Hands out unique anchors, suffixing collisions with -2, -3, ..."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def take(self, title: str) -> str:
        base = slugify(title)
        self._counts[base] = self._counts.get(base, 0) + 1
        n = self._counts[base]
        return base if n == 1 else f"{base}-{n}"
