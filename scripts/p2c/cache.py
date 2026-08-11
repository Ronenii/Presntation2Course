"""Feature C: cross-run cache for Phase 1 (outline) + Phase 2 (research)
output, keyed on the normalized PDFs' own content.

Never a correctness dependency: check() reports a miss (never raises) on
any read problem, and store() swallows any write problem and reports it
in its return value rather than raising -- a failed cache write must never
fail the run that produced the content it was trying to save.
"""

import hashlib
import json
import shutil
from pathlib import Path


def hash_normalized_dir(normalized_dir: Path) -> str:
    """SHA-256 of the concatenated bytes of every PDF in normalized_dir,
    sorted by filename so the result depends only on file content, never on
    filesystem iteration order."""
    digest = hashlib.sha256()
    for pdf in sorted(Path(normalized_dir).glob("*.pdf")):
        digest.update(pdf.read_bytes())
    return digest.hexdigest()


def cache_check(cache_root: Path, digest: str) -> dict:
    entry = Path(cache_root) / digest
    outline = entry / "outline.json"
    research_dir = entry / "research"
    try:
        if not outline.is_file():
            return {"hit": False}
        json.loads(outline.read_text(encoding="utf-8"))  # corrupt JSON -> miss
        if not research_dir.is_dir():
            return {"hit": False}
    except (OSError, ValueError):
        return {"hit": False}
    return {"hit": True, "outline": str(outline), "research_dir": str(research_dir)}


def cache_store(cache_root: Path, digest: str, outline: Path, research_dir: Path) -> dict:
    entry = Path(cache_root) / digest
    try:
        (entry / "research").mkdir(parents=True, exist_ok=True)
        shutil.copy2(outline, entry / "outline.json")
        for topic_file in Path(research_dir).glob("*.md"):
            shutil.copy2(topic_file, entry / "research" / topic_file.name)
    except OSError as exc:
        return {"stored": False, "error": str(exc)}
    return {"stored": True}


def main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="cache", description="Cross-run cache for outline/research.")
    sub = parser.add_subparsers(dest="command", required=True)

    check_p = sub.add_parser("check")
    check_p.add_argument("--normalized", required=True, type=Path)
    check_p.add_argument("--cache-root", required=True, type=Path)

    store_p = sub.add_parser("store")
    store_p.add_argument("--normalized", required=True, type=Path)
    store_p.add_argument("--cache-root", required=True, type=Path)
    store_p.add_argument("--outline", required=True, type=Path)
    store_p.add_argument("--research", required=True, type=Path)

    args = parser.parse_args(argv)
    digest = hash_normalized_dir(args.normalized)

    if args.command == "check":
        result = cache_check(args.cache_root, digest)
    else:
        result = cache_store(args.cache_root, digest, args.outline, args.research)
        result["hash"] = digest

    print(json.dumps(result, indent=2))
    return 0
