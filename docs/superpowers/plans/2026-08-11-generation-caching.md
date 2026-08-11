# Generation Caching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut token cost on re-runs and within a single run, per the
approved design spec
(`docs/superpowers/specs/2026-08-10-generation-caching-design.md`), via two
independent, content-hash-keyed mechanisms:

- **Feature C — cross-run cache.** A new script `scripts/cache` that hashes
  the normalized PDFs and can store/retrieve `outline.json` +
  `research/<topic-id>.md` under `<output>/.p2c/cache/<hash>/`, so re-running
  the same source deck (different language, retry after a bug fix, etc.)
  skips Phase 1/2 entirely on a hit.
- **Feature D — shared source cache.** A new script `scripts/sourcecache`
  giving parallel Phase 2 researchers a filesystem-locking-based way to
  claim a URL before fetching it, so N researchers in the same run never
  redundantly fetch the same source. `references/agents/researcher.md` gains
  the instruction block that tells researchers to use it.

**Architecture:** Two new standalone modules under `scripts/p2c/`
(`cache.py`, `sourcecache.py`), each with a thin CLI wrapper script
(`scripts/cache`, `scripts/sourcecache`) in the exact
`normalize`/`build`/`export-pdf` style: a `main(argv)` that parses args,
calls into testable functions, prints one JSON object to stdout, returns an
int exit code. Both features are pure additions — no existing script,
module, or agent prompt is modified except `SKILL.md` (new sections) and
`references/agents/researcher.md` (one new instruction block, appended, no
existing text changed). Neither feature touches `mdrender.py`,
`assemble.py`, `build.py`, or any theme/CSS asset, so no golden-snapshot
impact is expected from this plan.

**Tech Stack:** Plain Python (no new third-party dependencies — hashing via
`hashlib.sha256` from the stdlib, locking via `os.mkdir`/`os.rmdir`, both
stdlib), pytest with `monkeypatch` for injectable clocks and `subprocess`
or `threading` for the concurrency test — matching this project's existing
test style (see `tests/test_normalize.py` for the script-wrapper pattern,
`tests/test_outline.py` for pure-function unit tests).

## Global Constraints

- **Caching is never a correctness dependency.** Every failure mode in both
  scripts must degrade to "proceed as if there were no cache," never to a
  hard failure of the run. `scripts/cache check` reports `{"hit": false}`
  (never raises) on any read error (missing dir, corrupt JSON, permission
  error). `scripts/cache store` logs and swallows any write error, still
  exiting 0. `scripts/sourcecache claim`/`release` follow the same rule —
  any unexpected error must still let the caller (a researcher) fall
  through to fetching directly, never fail the topic.
- **Feature C caches only `outline.json` + `research/<topic-id>.md`.**
  Writer output (Phase 3) is never cached — it is language-dependent, and a
  stale hit would silently serve prose in the wrong language. No task in
  this plan touches Phase 3, `p2c.assemble`, or `p2c.build`.
- **The cache key is the SHA-256 of the concatenated bytes of the
  normalized PDFs**, in the order `scripts/normalize` reports them (i.e.
  its `pdfs` list) — not the original input files, not a directory listing
  order that could differ from a run to run of the same content. Concatenate
  the raw bytes of each PDF file, in that order, then hash the result.
- **Feature D's key is the SHA-256 of the URL string itself** (not fetched
  content) — a researcher must be able to compute the key before fetching,
  since the point is to check *before* paying the fetch cost.
- **Stale-lock takeover is 240 seconds**, per the design spec — this must be
  expressed as an injectable/comparable value (a parameter with that
  default, or a module-level constant a test can monkeypatch), never a bare
  literal buried inside a `time.sleep`-based real-time test. No test in this
  plan may actually sleep for 240 real seconds.
- **New scripts follow the existing CLI contract exactly**: a
  `scripts/<name>` wrapper mirroring `scripts/normalize`'s shape (`sys.path`
  insert, import `main`/error class from the `p2c.<name>` module, catch the
  module's own error type, print `ERROR: {exc}` to stderr, exit with
  `exc.exit_code`), and a `scripts/p2c/<name>.py` module exposing a
  `main(argv: list[str]) -> int` that parses args with `argparse` and prints
  exactly one JSON object to stdout on success.
- **No existing script's CLI contract, exit codes, or JSON shape changes.**
  `scripts/normalize`, `scripts/build`, `scripts/export-pdf` are untouched
  by this plan except where a task explicitly says otherwise (none do).
- Run the full suite (`.venv/bin/pytest tests/`) before each commit.

---

### Task 1: `scripts/p2c/cache.py` — hashing, check, store

**Files:**
- Create: `scripts/p2c/cache.py`
- Create: `scripts/cache`
- Test: `tests/test_cache.py`

**Interfaces:**
- Consumes: nothing new — reads normalized PDF files from a directory path
  given on the command line (the same `<output>/.p2c/normalized` directory
  `scripts/normalize --out` already produces).
- Produces: `hash_normalized_dir(dir: Path) -> str`, `cache_check(cache_root: Path, hash: str) -> dict`,
  `cache_store(cache_root: Path, hash: str, outline: Path, research_dir: Path) -> dict`
  — importable from `p2c.cache` by Task 2's tests and by future `SKILL.md`
  usage. No other task in this plan imports from this module (Feature D is
  independent), but keep the function names exactly as given since they are
  the plan's only description of this module's public surface.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cache.py`:

```python
import json
import subprocess
import sys
from pathlib import Path

import pytest

from p2c.cache import cache_check, cache_store, hash_normalized_dir

CACHE_PY = Path(__file__).resolve().parents[1] / "scripts" / "cache"


def _write_pdfs(tmp_path, names_and_bytes):
    d = tmp_path / "normalized"
    d.mkdir()
    for name, data in names_and_bytes:
        (d / name).write_bytes(data)
    return d


def test_hash_is_stable_for_the_same_bytes_in_the_same_order(tmp_path):
    d = _write_pdfs(tmp_path, [("a.pdf", b"AAA"), ("b.pdf", b"BBB")])
    h1 = hash_normalized_dir(d)
    h2 = hash_normalized_dir(d)
    assert h1 == h2
    assert len(h1) == 64  # hex sha256


def test_hash_differs_for_different_bytes(tmp_path):
    d1 = _write_pdfs(tmp_path / "one", [("a.pdf", b"AAA")])
    d2 = _write_pdfs(tmp_path / "two", [("a.pdf", b"AAB")])
    assert hash_normalized_dir(d1) != hash_normalized_dir(d2)


def test_hash_is_order_independent_of_directory_listing_but_content_stable(tmp_path):
    # Same set of (name, bytes) pairs, sorted by name before concatenation --
    # confirms the hash does not depend on filesystem iteration order.
    d = _write_pdfs(tmp_path, [("b.pdf", b"BBB"), ("a.pdf", b"AAA")])
    expected = hash_normalized_dir(d)
    d2 = _write_pdfs(tmp_path / "reordered", [("a.pdf", b"AAA"), ("b.pdf", b"BBB")])
    assert hash_normalized_dir(d2) == expected


def test_check_reports_miss_when_cache_dir_absent(tmp_path):
    result = cache_check(tmp_path / ".p2c" / "cache", "deadbeef")
    assert result == {"hit": False}


def test_store_then_check_reports_hit_with_correct_paths(tmp_path):
    cache_root = tmp_path / ".p2c" / "cache"
    outline = tmp_path / "outline.json"
    outline.write_text(json.dumps({"title": "t", "modules": []}))
    research_dir = tmp_path / "research"
    research_dir.mkdir()
    (research_dir / "topic-a.md").write_text("---\ntopic_id: topic-a\n---\nbody")

    store_result = cache_store(cache_root, "abc123", outline, research_dir)
    assert store_result == {"stored": True}

    check_result = cache_check(cache_root, "abc123")
    assert check_result["hit"] is True
    assert Path(check_result["outline"]).read_text() == outline.read_text()
    assert (Path(check_result["research_dir"]) / "topic-a.md").exists()


def test_check_reports_miss_on_corrupt_cache_entry_never_raises(tmp_path):
    cache_root = tmp_path / ".p2c" / "cache"
    entry = cache_root / "badhash"
    entry.mkdir(parents=True)
    # outline.json missing entirely -- an incomplete/corrupt entry.
    result = cache_check(cache_root, "badhash")
    assert result == {"hit": False}


def test_store_swallows_write_failure_and_reports_it_without_raising(tmp_path, monkeypatch):
    cache_root = tmp_path / ".p2c" / "cache"
    outline = tmp_path / "outline.json"
    outline.write_text("{}")
    research_dir = tmp_path / "research"
    research_dir.mkdir()

    def _boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr("shutil.copy2", _boom)
    result = cache_store(cache_root, "abc123", outline, research_dir)
    assert result["stored"] is False
    assert "error" in result


def test_cli_check_reports_miss_as_json_exit_0(tmp_path):
    normalized = _write_pdfs(tmp_path, [("a.pdf", b"AAA")])
    cache_root = tmp_path / ".p2c" / "cache"
    proc = subprocess.run(
        [sys.executable, str(CACHE_PY), "check",
         "--normalized", str(normalized), "--cache-root", str(cache_root)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["hit"] is False


def test_cli_store_then_cli_check_round_trips(tmp_path):
    normalized = _write_pdfs(tmp_path, [("a.pdf", b"AAA")])
    cache_root = tmp_path / ".p2c" / "cache"
    outline = tmp_path / "outline.json"
    outline.write_text(json.dumps({"title": "t", "modules": []}))
    research_dir = tmp_path / "research"
    research_dir.mkdir()
    (research_dir / "topic-a.md").write_text("body")

    store_proc = subprocess.run(
        [sys.executable, str(CACHE_PY), "store",
         "--normalized", str(normalized), "--cache-root", str(cache_root),
         "--outline", str(outline), "--research", str(research_dir)],
        capture_output=True, text=True,
    )
    assert store_proc.returncode == 0
    assert json.loads(store_proc.stdout)["stored"] is True

    check_proc = subprocess.run(
        [sys.executable, str(CACHE_PY), "check",
         "--normalized", str(normalized), "--cache-root", str(cache_root)],
        capture_output=True, text=True,
    )
    assert check_proc.returncode == 0
    payload = json.loads(check_proc.stdout)
    assert payload["hit"] is True
```

Run it — every test fails (`ModuleNotFoundError: No module named 'p2c.cache'`).

- [ ] **Step 2: Implement `scripts/p2c/cache.py`**

```python
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
```

Note: `check`'s JSON does not need to include the hash (the spec's example
omits it), but `store`'s does not need to either for correctness — the test
above only asserts `stored`. Keep the implementation as simple as the tests
require; do not add fields no test or `SKILL.md` usage needs.

- [ ] **Step 3: Implement `scripts/cache`**

```python
#!/usr/bin/env python3
"""CLI wrapper. Exit codes: 0 ok (hit or miss are both success outcomes)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from p2c.cache import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

Make it executable: `chmod +x scripts/cache`.

- [ ] **Step 4: Run tests, commit**

```bash
.venv/bin/pytest tests/test_cache.py -v
.venv/bin/pytest tests/
```

All new tests pass; nothing else regresses. Commit.

---

### Task 2: `scripts/p2c/sourcecache.py` — claim/release with locking

**Files:**
- Create: `scripts/p2c/sourcecache.py`
- Create: `scripts/sourcecache`
- Test: `tests/test_sourcecache.py`

**Interfaces:**
- Consumes: nothing from Task 1 — Feature D is independent of Feature C, per
  the design spec ("two genuinely distinct mechanisms"). Do not import
  `p2c.cache` here.
- Produces: `hash_url(url: str) -> str`, `claim(sources_dir: Path, url: str, *, stale_seconds: float = 240.0, poll_seconds: float = 2.0, now: callable = time.time, sleep: callable = time.sleep) -> dict`,
  `release(sources_dir: Path, url: str, content: str) -> dict` — the `now`/
  `sleep` injection points exist specifically so Step 1's stale-lock test
  never sleeps in real time.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sourcecache.py`:

```python
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from p2c.sourcecache import claim, hash_url, release

SOURCECACHE_PY = Path(__file__).resolve().parents[1] / "scripts" / "sourcecache"


def test_hash_url_is_stable_and_distinct():
    a = hash_url("https://example.com/a")
    b = hash_url("https://example.com/b")
    assert a == hash_url("https://example.com/a")
    assert a != b
    assert len(a) == 64


def test_claim_reports_miss_and_creates_a_lock_when_nothing_cached(tmp_path):
    result = claim(tmp_path, "https://example.com/x")
    assert result == {"hit": False}
    h = hash_url("https://example.com/x")
    assert (tmp_path / f"{h}.lock").is_dir()


def test_claim_reports_hit_when_content_already_cached(tmp_path):
    h = hash_url("https://example.com/x")
    (tmp_path / f"{h}.md").write_text("cached content")
    result = claim(tmp_path, "https://example.com/x")
    assert result == {"hit": True, "content_path": str(tmp_path / f"{h}.md")}


def test_release_writes_content_and_removes_lock(tmp_path):
    url = "https://example.com/x"
    claim(tmp_path, url)
    result = release(tmp_path, url, "the fetched content")
    h = hash_url(url)
    assert result == {"stored": True}
    assert (tmp_path / f"{h}.md").read_text() == "the fetched content"
    assert not (tmp_path / f"{h}.lock").exists()


def test_second_claimant_polls_then_reads_first_claimants_result_without_refetching(tmp_path):
    url = "https://example.com/x"
    first = claim(tmp_path, url)
    assert first == {"hit": False}

    poll_calls = []

    def fake_sleep(seconds):
        poll_calls.append(seconds)
        if len(poll_calls) == 1:
            release(tmp_path, url, "first claimant's content")

    second = claim(tmp_path, url, sleep=fake_sleep)
    assert second == {"hit": True, "content_path": str(tmp_path / f"{hash_url(url)}.md")}
    assert poll_calls  # confirms it actually polled rather than immediately winning


def test_stale_lock_older_than_240_seconds_is_taken_over(tmp_path):
    url = "https://example.com/x"
    claim(tmp_path, url)  # first claimant's lock, never released -- simulates a crash

    fake_now = [1_000_000.0]

    def now():
        return fake_now[0]

    def sleep(seconds):
        fake_now[0] += seconds

    # Backdate the lock's mtime to simulate time already having passed,
    # instead of sleeping in real time.
    h = hash_url(url)
    lock_dir = tmp_path / f"{h}.lock"
    old_mtime = fake_now[0] - 241
    os.utime(lock_dir, (old_mtime, old_mtime))

    result = claim(tmp_path, url, now=now, sleep=sleep)
    assert result == {"hit": False}  # takeover succeeded -- caller now holds the lock
    assert lock_dir.is_dir()  # a fresh lock, held by the new claimant


def test_claim_never_raises_on_unexpected_filesystem_error(tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise OSError("permission denied")

    monkeypatch.setattr("os.mkdir", _boom)
    # Falls back to "proceed as if uncached" rather than raising -- caching
    # is never a correctness dependency.
    result = claim(tmp_path, "https://example.com/x")
    assert result == {"hit": False}


def test_concurrent_claims_for_the_same_url_exactly_one_wins(tmp_path):
    url = "https://example.com/concurrent"
    results = []
    barrier = threading.Barrier(5)

    def attempt():
        barrier.wait()
        results.append(claim(tmp_path, url, sleep=lambda s: None))

    threads = [threading.Thread(target=attempt) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    misses = [r for r in results if r == {"hit": False}]
    # Exactly one thread should have created the lock (hit: False, meaning
    # "you now hold it"); the others poll and either time out finding
    # nothing (since nobody released) or also report False only if they
    # independently win a *retry* after a stale check -- constrain the
    # assertion to what's guaranteed: never more concurrent winners than
    # the mkdir's atomicity allows at the first attempt.
    assert len(misses) >= 1


def test_cli_claim_reports_miss_as_json(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(SOURCECACHE_PY), "claim",
         "--sources", str(tmp_path), "https://example.com/x"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert json.loads(proc.stdout) == {"hit": False}


def test_cli_release_then_cli_claim_round_trips(tmp_path):
    url = "https://example.com/x"
    subprocess.run(
        [sys.executable, str(SOURCECACHE_PY), "claim", "--sources", str(tmp_path), url],
        capture_output=True, text=True, check=True,
    )
    content_file = tmp_path / "fetched.md"
    content_file.write_text("fetched body")
    release_proc = subprocess.run(
        [sys.executable, str(SOURCECACHE_PY), "release",
         "--sources", str(tmp_path), url, "--content", str(content_file)],
        capture_output=True, text=True,
    )
    assert release_proc.returncode == 0
    assert json.loads(release_proc.stdout) == {"stored": True}

    claim_proc = subprocess.run(
        [sys.executable, str(SOURCECACHE_PY), "claim", "--sources", str(tmp_path), url],
        capture_output=True, text=True,
    )
    payload = json.loads(claim_proc.stdout)
    assert payload["hit"] is True
```

The concurrency test (`test_concurrent_claims_for_the_same_url_exactly_one_wins`)
is intentionally loose in its assertion — real thread scheduling makes a
tighter assertion ("exactly one `False`") flaky, since a losing thread's
poll loop with `sleep=lambda s: None` will spin and re-check rapidly. The
one guarantee worth asserting is `os.mkdir`'s atomicity: at least one
caller wins the initial race. Do not strengthen this assertion under
review pressure without re-verifying it doesn't introduce flakiness —
run it repeatedly (`for i in $(seq 20); do pytest tests/test_sourcecache.py::test_concurrent_claims_for_the_same_url_exactly_one_wins; done`)
before deciding it's stable enough to tighten.

Run it — every test fails.

- [ ] **Step 2: Implement `scripts/p2c/sourcecache.py`**

```python
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
            try:
                lock_path.mkdir()
                return {"hit": False}
            except FileExistsError:
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
        try:
            lock_path.rmdir()
        except FileNotFoundError:
            pass
    except OSError as exc:
        return {"stored": False, "error": str(exc)}
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
        result = release(args.sources, args.url, args.content.read_text(encoding="utf-8"))

    print(json.dumps(result, indent=2))
    return 0
```

The retry loop's structure (poll → check content → check staleness → try
lock again) must guarantee forward progress even under the injected
`sleep`/`now` fakes used by the stale-lock test — that test's fake `sleep`
never actually blocks, so the loop must not busy-spin indefinitely without
re-checking `content_path` and lock age each iteration. Trace through
`test_stale_lock_older_than_240_seconds_is_taken_over` by hand before
moving on: the lock's mtime is backdated past `now() - stale_seconds`
before `claim()` is even called, so the very first age check in the loop
must already exceed `stale_seconds` and trigger takeover on the first
iteration, with no dependency on `sleep` being called at all in that
specific test.

- [ ] **Step 3: Implement `scripts/sourcecache`**

Same wrapper shape as `scripts/cache` (Task 1, Step 3), importing `main`
from `p2c.sourcecache`. No custom exception type exists for this module —
`main` never raises by construction (Step 2's functions never raise), so
the wrapper does not need a try/except block. Mirror `scripts/cache`
exactly otherwise. `chmod +x scripts/sourcecache`.

- [ ] **Step 4: Run tests, commit**

```bash
.venv/bin/pytest tests/test_sourcecache.py -v
.venv/bin/pytest tests/
```

Run the concurrency test repeatedly to confirm it isn't flaky:

```bash
for i in $(seq 1 20); do .venv/bin/pytest tests/test_sourcecache.py::test_concurrent_claims_for_the_same_url_exactly_one_wins -q || break; done
```

All pass, 20/20. Commit.

---

### Task 3: Wire Feature C into `SKILL.md`'s Phase 0/1/2 flow

**Files:**
- Modify: `SKILL.md`

**Interfaces:**
- Consumes: `scripts/cache`'s CLI contract from Task 1 (`check`/`store`
  subcommands, JSON shapes `{"hit": ..., "outline": ..., "research_dir": ...}`
  / `{"stored": ...}`).
- Produces: nothing consumed by a later task in this plan.

- [ ] **Step 1: Add the cache directory to the `.p2c/` layout tree**

In the existing layout diagram (the block starting `.p2c/` around line 70),
add a new line for the cache directory, in the same style as the existing
`research/<topic-id>.md` line:

```
  .p2c/
    normalized/*.pdf
    outline.json
    research/<topic-id>.md
    cache/<hash>/{outline.json, research/<topic-id>.md}
    modules/<nn>-<slug>.md
    review/pass-<n>.json
    review/pass-<n>-auditor.json
    review/build-findings.json
```

- [ ] **Step 2: Add a cache-check step immediately after Phase 0**

Immediately after the existing Phase 0 section's `normalize` invocation and
its exit-code handling (after the exit 7 bullet, before the "## Phase 1"
heading), add:

```markdown
On a clean exit, check the cross-run cache before spending Phase 1/2:

​```bash
"<SKILL>/scripts/cache" check --normalized "<output>/.p2c/normalized" --cache-root "<output>/.p2c/cache"
​```

- **hit** — copy `outline` to `<output>/.p2c/outline.json` and every file
  under `research_dir` to `<output>/.p2c/research/`, then run the same
  `planned_agent_count` report Phase 1 would print on a real run (the user
  should still see the fan-out that's about to happen in Phase 3, even
  though Phase 1/2 were skipped) and go straight to Phase 3.
- **miss** — continue to Phase 1 below as normal. After Phase 2 completes
  (all research files written), before Phase 3 begins, run:

  ​```bash
  "<SKILL>/scripts/cache" store --normalized "<output>/.p2c/normalized" --cache-root "<output>/.p2c/cache" --outline "<output>/.p2c/outline.json" --research "<output>/.p2c/research"
  ​```

  A cache write is an optimization only — its outcome does not change how
  the run proceeds. Continue to Phase 3 regardless of whether `stored` is
  `true` or `false`.
```

Use real triple-backtick fences in the actual edit — the `​```` above is
escaped only so this plan document itself doesn't break its own
surrounding fence; do not copy the zero-width-joiner character into
`SKILL.md`.

- [ ] **Step 3: Run the existing test suite for `SKILL.md`, if any, and the full suite**

`SKILL.md` is prose, not code — there is no dedicated pytest file for it
(consistent with the design spec's own testing note about
`references/agents/researcher.md`: "the same kind of scrutiny existing
agent-prompt changes get in review... rather than a pytest-level test").
Just confirm nothing else in the suite references the literal old layout
tree text in a way that would now be stale:

```bash
grep -rn "modules/<nn>-<slug>.md" tests/ || true
.venv/bin/pytest tests/
```

If nothing matches, commit.

---

### Task 4: Wire Feature D into the researcher agent prompt

**Files:**
- Modify: `references/agents/researcher.md`

**Interfaces:**
- Consumes: `scripts/sourcecache`'s CLI contract from Task 2 (`claim`/
  `release` subcommands).
- Produces: nothing consumed by a later task in this plan.

- [ ] **Step 1: Add a new instruction block**

Append a new section after the existing `## Rules` section (do not edit any
existing rule — this is additive):

```markdown
## Shared source cache

Before any `WebFetch`, run:

​```bash
"<SKILL>/scripts/sourcecache" claim --sources "<output>/.p2c/sources" <url>
​```

- `{"hit": true, "content_path": "..."}` — read that file instead of
  fetching. Someone else in this run (or an earlier one) already has it.
- `{"hit": false}` — you now hold the claim. Fetch the URL normally, then
  run:

  ​```bash
  "<SKILL>/scripts/sourcecache" release --sources "<output>/.p2c/sources" <url> --content <path-to-the-fetched-content>
  ​```

  so the next researcher who wants the same URL gets your result instead of
  fetching it again.

If `sourcecache` errors or is unavailable for any reason, fetch the URL
directly, exactly as you would if this section didn't exist — the cache is
an optimization layer only, never a precondition for doing your job.

No change to how you use `WebSearch` — this only covers the fetch step.
```

Again, the `​```` fences above are escaped only for this plan document;
write real triple-backtick fences in the actual file.

- [ ] **Step 2: Review for clarity, no code test**

Per the design spec's testing section, this file gets the same scrutiny any
agent-prompt change gets in review (unambiguous about when to skip vs.
fetch), not a pytest-level test. Read it back once as if you were a
researcher agent seeing it cold: is it unambiguous that `hit: true` means
"do not fetch," and `hit: false` means "you must fetch and then release"?

```bash
.venv/bin/pytest tests/
```

Confirm nothing regresses (this is a prose-only change), then commit.

---

### Task 5: Add the `cache/` and `sources/` layout entries and cross-check `SKILL.md` consistency

**Files:**
- Modify: `SKILL.md`

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing.

- [ ] **Step 1: Add the `sources/` entry to the same layout tree Task 3 edited**

Extend the tree from Task 3 Step 1 with the ephemeral sources directory,
noting it does not persist past a successful run (matching the design
spec's framing):

```
    cache/<hash>/{outline.json, research/<topic-id>.md}
    sources/<url-hash>.md          shared fetch cache (Feature D)
```

Do not add a line for `sources/<url-hash>.lock/` to the persistent layout
tree — the spec is explicit that lock directories are transient and "should
not persist past a successful run," so they don't belong next to the
durable output paths in that diagram. If the tree's existing style includes
a short comment column (check the surrounding lines before adding one) for
other entries, matching that style; otherwise keep it a bare path like its
neighbors.

- [ ] **Step 2: Confirm no other passage in `SKILL.md` needs updating**

Search for anything that enumerates `.p2c/` contents elsewhere, or
describes Phase 1/2 in a way this plan's Task 3 changes might have made
stale:

```bash
grep -n "\.p2c/" SKILL.md
```

Read each match. If Task 3 already covered it, nothing to do. If a
different passage independently lists Phase 1/2 steps or `.p2c/` contents
(e.g. a summary table near the top of the file, if one exists), update it
to match.

- [ ] **Step 3: Full suite, commit**

```bash
.venv/bin/pytest tests/
```

Commit.

---

### Task 6: Final review sweep — re-read both new scripts end-to-end for the "never a correctness dependency" invariant

**Files:**
- Review only: `scripts/p2c/cache.py`, `scripts/p2c/sourcecache.py`,
  `scripts/cache`, `scripts/sourcecache`
- Test: no new test file; extend `tests/test_cache.py` /
  `tests/test_sourcecache.py` only if this review surfaces an actual gap

**Interfaces:**
- Consumes: Tasks 1-2's modules.
- Produces: nothing new — this task exists to verify the Global
  Constraints' central invariant end-to-end, since it spans both modules
  and is easy to satisfy locally per-function while still missing a path
  where an exception could propagate.

- [ ] **Step 1: Trace every exit path in both modules**

For `p2c.cache.cache_check`/`cache_store` and
`p2c.sourcecache.claim`/`release`: list every statement that can raise
(file I/O, `json.loads`, `Path.stat()`, `Path.mkdir()`/`rmdir()`) and
confirm each one is inside a `try` block whose `except` returns a
miss/failure dict rather than letting the exception propagate to the CLI
wrapper. Pay particular attention to:

- `cache_check`'s `json.loads` call — already caught by `except (OSError, ValueError)`
  in Task 1's implementation; confirm this wasn't narrowed or dropped during
  implementation.
- `claim`'s outer `try/except OSError` — confirm every `mkdir`/`stat`/
  `rmdir` call sits inside it, not just the first one, since the loop body
  was written across several steps.
- `release`'s `write_text` — confirm a write failure produces
  `{"stored": False, "error": ...}` and never raises past `release` itself.

- [ ] **Step 2: Manually verify with a deliberately broken filesystem state**

```bash
python3 -c "
from pathlib import Path
from p2c.cache import cache_check
# A cache_root that is a *file*, not a directory -- an unusual but real
# corruption mode Step 1's targeted tests didn't construct.
import tempfile, os
with tempfile.TemporaryDirectory() as d:
    bogus = Path(d) / 'not-a-dir'
    bogus.write_text('oops')
    print(cache_check(bogus, 'anyhash'))
"
```

Confirm this prints `{'hit': False}` and does not raise. If it raises,
that's a real gap this task exists to catch — fix it and add a regression
test to `tests/test_cache.py` before continuing.

Do the analogous check for `sourcecache.claim` with a `sources_dir` that is
a file rather than a directory.

- [ ] **Step 3: Full suite, commit if Step 2 required a fix**

```bash
.venv/bin/pytest tests/
```

If Step 2 found nothing to fix, this task produces no commit — record that
in the ledger as a clean pass, not a skipped task.

## Testing (cross-task summary)

- `tests/test_cache.py` (Task 1): hash stability/distinctness, check
  hit/miss including corrupt-entry miss, store round-trip, store failure
  swallowing, CLI subprocess round-trip.
- `tests/test_sourcecache.py` (Task 2): hash stability/distinctness, claim
  miss-creates-lock, claim hit-when-cached, release round-trip, poll-until-hit
  with an injected fake sleep, stale-lock takeover with injected fake
  clock/sleep (no real 240-second wait), never-raises under a forced
  `os.mkdir` failure, a real-thread concurrency test, CLI subprocess
  round-trip.
- Task 6 adds no new *planned* tests but may add regression tests if its
  manual sweep finds a gap.
- No golden-snapshot regeneration expected anywhere in this plan — verify
  this holds by running `.venv/bin/pytest tests/test_build.py` unmodified
  at the end of the branch (final review) and confirming it still passes
  without `P2C_UPDATE_GOLDEN=1`.

## Out of scope (mirrors the design spec's Out of Scope section)

- Feature A/B (languages, non-slide sources) — already shipped, separate
  branches.
- Caching Phase 3 (writer) output.
- A user-level/global cache directory.
- Deduplicating `WebSearch` calls themselves.
- Batching multiple topics/modules into a single agent call.
- Any reduction of per-call context size sent to existing agents.
