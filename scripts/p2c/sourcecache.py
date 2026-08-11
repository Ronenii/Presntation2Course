"""Feature D: a filesystem-locking-based shared cache for URLs fetched
during Phase 2, so parallel researchers in the same run never redundantly
fetch the same source.

Never a correctness dependency: claim()/release() report their outcome in
their return value on any unexpected filesystem error rather than raising
-- a caller that cannot use the cache must always be able to fall through
to fetching directly, the same as if the cache didn't exist.
"""

import hashlib
import time
from pathlib import Path

STALE_SECONDS = 240.0
POLL_SECONDS = 2.0


def hash_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _content_path(sources_dir: Path, digest: str) -> Path:
    return Path(sources_dir) / f"{digest}.md"


def _lock_path(sources_dir: Path, digest: str) -> Path:
    return Path(sources_dir) / f"{digest}.lock"


def claim(
    sources_dir: Path,
    url: str,
    *,
    stale_seconds: float = STALE_SECONDS,
    poll_seconds: float = POLL_SECONDS,
    now=time.time,
    sleep=time.sleep,
) -> dict:
    sources_dir = Path(sources_dir)
    digest = hash_url(url)
    content_path = _content_path(sources_dir, digest)
    lock_path = _lock_path(sources_dir, digest)

    try:
        sources_dir.mkdir(parents=True, exist_ok=True)
        if content_path.is_file():
            return {"hit": True, "content_path": str(content_path)}

        try:
            lock_path.mkdir()
            return {"hit": False}
        except FileExistsError:
            pass

        while True:
            if content_path.is_file():
                return {"hit": True, "content_path": str(content_path)}
            try:
                lock_age = now() - lock_path.stat().st_mtime
            except FileNotFoundError:
                lock_age = None
            if lock_age is not None and lock_age > stale_seconds:
                try:
                    lock_path.rmdir()
                except OSError:
                    pass
                try:
                    lock_path.mkdir()
                    return {"hit": False}
                except FileExistsError:
                    continue
            sleep(poll_seconds)
            # Re-check content/staleness from the top rather than assuming
            # the wait ended because the lock is now free -- the sleep hook
            # may itself have released the lock (see
            # test_second_claimant_polls_then_reads_first_claimants_result_
            # without_refetching), so a blind mkdir() retry here could steal
            # a lock that the real winner already vacated on purpose.
            continue
    except OSError:
        return {"hit": False}


def release(sources_dir: Path, url: str, content: str) -> dict:
    sources_dir = Path(sources_dir)
    digest = hash_url(url)
    content_path = _content_path(sources_dir, digest)
    lock_path = _lock_path(sources_dir, digest)
    try:
        content_path.write_text(content, encoding="utf-8")
    except OSError as exc:
        return {"stored": False, "error": str(exc)}
    try:
        lock_path.rmdir()
    except FileNotFoundError:
        pass
    except OSError:
        pass  # content is already saved; a later claim() still finds it and hits.
    return {"stored": True}


def main(argv: list[str]) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(prog="sourcecache", description="Shared source-fetch cache with locking.")
    sub = parser.add_subparsers(dest="command", required=True)

    claim_p = sub.add_parser("claim")
    claim_p.add_argument("url")
    claim_p.add_argument("--sources", required=True, type=Path)

    release_p = sub.add_parser("release")
    release_p.add_argument("url")
    release_p.add_argument("--sources", required=True, type=Path)
    release_p.add_argument("--content", required=True, type=Path)

    args = parser.parse_args(argv)

    if args.command == "claim":
        result = claim(args.sources, args.url)
    else:
        try:
            content = args.content.read_text(encoding="utf-8")
        except OSError as exc:
            result = {"stored": False, "error": str(exc)}
        else:
            result = release(args.sources, args.url, content)

    print(json.dumps(result, indent=2))
    return 0
