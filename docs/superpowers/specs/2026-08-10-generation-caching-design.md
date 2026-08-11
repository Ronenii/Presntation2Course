# v1.3.0 — Generation caching (cross-run + shared source cache) — Design

**Date:** 2026-08-10
**Status:** Approved

## Context

The third feature deferred from the v1.3.0-bugfixes batch was "ways to make
course generation less expensive tokenwise," via caching and source
reusability. Two genuinely distinct mechanisms fall out of that goal, both
content-hash-keyed, both grouped here:

1. **Cross-run cache.** Re-running the same source deck — to try a
   different `<language>`, to retry after fixing a downstream bug, or to
   regenerate after a partial failure — currently reprocesses Phase 1
   (summarizer, 1 agent) and Phase 2 (researcher, N agents, one per topic)
   from scratch every time, even though both are entirely
   **language-independent**: `outline.json` and every `research/<topic-id>.md`
   depend only on the source deck's own content. There is currently zero
   caching infrastructure anywhere in the codebase.
2. **Shared source cache.** Within a single run, Phase 2 dispatches one
   researcher per topic, all in parallel, each with independent `WebSearch`/
   `WebFetch` access. A course or paper generally sits in one domain, so
   topics frequently need the same underlying sources (a textbook chapter, a
   standard, a reference page) — today, N researchers can each
   independently search for and fetch the identical URL, paying the fetch
   cost N times with no coordination.

Both are new, currently-nonexistent state, and both live under
`<output>/.p2c/` (run-scoped, matching the project's existing "everything
under `.p2c/` is this run's working state" convention) rather than a
user-level cache directory — a fresh `<output>` gets no cross-run benefit
from a *different* prior output directory, which is an accepted tradeoff in
exchange for not needing to reason about a shared location across unrelated
runs.

## Feature C: cross-run cache

### What's cached

`outline.json` and every `research/<topic-id>.md` file — Phase 1 and Phase 2
output, and nothing past it. Writer output (Phase 3) is explicitly **never**
cached: it depends on `<language>`, so a cache hit there would silently
serve prose in the wrong language on a language-changed re-run. This mirrors
the reasoning already documented in `SKILL.md`'s Phase 3 section about
computing filenames explicitly rather than letting anything downstream
re-derive language-sensitive values.

### Key

SHA-256 of the concatenated bytes of the **normalized** PDFs (i.e., computed
after Phase 0, on the same files the summarizer will read) — not the
original input files. This means a `.pptx` and its LibreOffice-converted
PDF equivalent, or a `.docx`/`.md` source and its rendered-PDF equivalent
(per the companion input/output-expansion spec), hit the same cache entry
as long as the resulting page content is identical, which matches the
intent ("this is about source *content*, not source *format*").

### Storage

```
<output>/.p2c/cache/<hash>/
  outline.json
  research/<topic-id>.md   (one per topic)
```

### Mechanism

New script `scripts/p2c/cache.py`, invoked as `scripts/cache`, following the
same "script decides, orchestrator branches on its JSON" pattern as
`normalize`/`build`/`export-pdf`:

- **`scripts/cache check --normalized <dir>`** — hashes the normalized PDFs,
  reports hit/miss:
  ```json
  {"hit": true, "outline": "<output>/.p2c/cache/<hash>/outline.json",
   "research_dir": "<output>/.p2c/cache/<hash>/research"}
  ```
  On hit, `SKILL.md` copies these into `<output>/.p2c/outline.json` and
  `<output>/.p2c/research/`, prints the module/topic counts and
  `planned_agent_count` exactly as it would after a real Phase 1 run (the
  user should still see what's about to happen in Phase 3 even on a cache
  hit), and skips straight to Phase 3.
- **`scripts/cache store --normalized <dir> --outline <path> --research <dir>`**
  — on a miss, after Phase 1/2 complete normally, copies the fresh output
  into the cache directory under that hash for next time.

### Failure handling

Caching is an optimization, never a correctness dependency. Any error in
`check` (unreadable cache dir, hash mismatch, corrupt cached JSON) is
reported as a miss, never a hard failure — the run proceeds through Phase
1/2 normally. Any error in `store` (disk full, permissions) is logged and
swallowed — a failed cache write never fails the run that produced the
content it was trying to save.

### `SKILL.md` changes

- New tree entry under the existing `.p2c/` layout diagram:
  `cache/<hash>/{outline.json, research/<topic-id>.md}`.
- Phase 0 section: immediately after `normalize` succeeds, run
  `scripts/cache check`. Branch: hit → copy + report + skip to Phase 3; miss
  → continue to Phase 1 as today, then run `scripts/cache store` once Phase 2
  completes, before Phase 3 begins.

## Feature D: shared source cache for researchers

### What's cached

The **fetched content** of a URL — not the search itself. `WebSearch`
queries stay fully independent per topic (queries genuinely differ even
within one domain — "TLB miss handling" and "page replacement policies" are
different searches that may still converge on the same textbook chapter),
so only the expensive fetch-and-read-a-full-page step is deduplicated.

### Key and storage

Hash of the fetched URL, stored at `<output>/.p2c/sources/<hash>.md` (the
fetched content, in whatever form the researcher would otherwise have held
it in context).

### Coordination: locking

Researchers are separate subagent dispatches, not threads in one process —
coordination has to go through the filesystem. Before fetching a URL, a
researcher must claim it first, to prevent two parallel researchers from
independently fetching the same new URL at the same moment:

1. Check `sources/<hash>.md`. If present, use it — no fetch.
2. If absent, attempt `os.mkdir(sources/<hash>.lock)`. `mkdir` is atomic on
   every POSIX filesystem — exactly one concurrent caller can succeed.
3. **On success:** fetch the URL, write `sources/<hash>.md`, then
   `os.rmdir(sources/<hash>.lock)`.
4. **On failure (`FileExistsError`, lock already held):** poll every ~2
   seconds for `sources/<hash>.md` to appear. If it appears, use it.
5. **Stale-lock takeover:** if the lock directory's mtime is older than
   **240 seconds** while polling, treat the lock as abandoned (its holder
   crashed, timed out, or was killed — a real possibility, since `SKILL.md`
   already has a failure-handling entry for "a subagent produces no file"),
   remove it, and proceed as if the claim had succeeded (step 3) — no
   orchestrator involvement, self-healing.

240 seconds is comfortably longer than any single `WebFetch` should take, so
a live, legitimately-slow fetch is never mistaken for an abandoned one under
normal conditions, while a genuinely crashed researcher's lock is reclaimed
well within the run's own timescale rather than deadlocking every other
topic that happens to want the same source.

### Mechanism

New helper script `scripts/p2c/sourcecache.py`, two subcommands — a
lock-broker script in the same "agent shells out to tested code, never
hand-rolls the mechanism itself" style as every other script in this
codebase, rather than asking the researcher agent to implement filesystem
locking inline:

- **`sourcecache claim <url>`** — runs the full steps 1-5 above (check for
  an existing cache hit; if none, attempt the lock; if the lock is held,
  poll, applying the 240-second stale-lock takeover) and reports one of two
  outcomes as JSON: `{"hit": true, "content_path": "sources/<hash>.md"}` (a
  cached file already exists — read it, do not fetch), or
  `{"hit": false}` (the caller now holds the lock and must fetch).
- **`sourcecache release <url> --content <path-to-fetched-content>`** —
  writes the fetched content to `sources/<hash>.md`, then removes the lock
  directory (step 3). Called only after a `{"hit": false}` claim.

`references/agents/researcher.md` gains a new instruction block: before any
`WebFetch`, run `sourcecache claim <url>`; on `hit: true`, read
`content_path` instead of fetching; on `hit: false`, fetch normally, then
run `sourcecache release <url>` with the fetched content. No change to
`WebSearch` usage or to any other part of the researcher's existing
instructions.

### Failure handling

Same principle as Feature C: if `sourcecache claim`/`release` errors for any
reason, the researcher falls back to fetching directly (as if it always had)
rather than failing the topic — the cache is strictly an optimization layer
sitting in front of behavior that already works today.

### `SKILL.md` changes

New tree entry under `.p2c/`: `sources/<url-hash>.md` (and transient
`sources/<url-hash>.lock/` directories, which should not persist past a
successful run — noted as ephemeral, not part of the run's durable output).

## Testing

- `test_cache.py`: hash stability (same normalized bytes → same hash,
  different bytes → different hash), hit/miss reporting, `store` writing the
  expected files, and each failure-handling case (missing dir → miss,
  simulated write failure → swallowed, run continues).
- `test_sourcecache.py`: claim/release happy path, the poll-until-hit path
  (two simulated callers, second one waits then reads the first's cached
  result rather than re-fetching), and the 240-second stale-lock takeover —
  using an injectable/mockable clock rather than a real 4-minute sleep, so
  the test suite doesn't pay that cost. A concurrency test using real
  subprocesses or threads attempting simultaneous `claim` calls against the
  same hash, asserting exactly one succeeds.
- `references/agents/researcher.md`'s updated instructions get the same
  kind of scrutiny existing agent-prompt changes get in review (clarity,
  no ambiguity about when to skip vs. perform a fetch) rather than a
  pytest-level test, since it's prose read by an LLM, not code.
- No golden-snapshot impact expected — neither feature touches `mdrender.py`
  or any rendered HTML/CSS.

## Out of scope

- The input/output expansion feature (languages, non-slide sources) —
  separate design (see companion spec, same date).
- Caching writer output (Phase 3) — explicitly rejected; it is
  language-dependent and a stale hit would silently serve the wrong
  language.
- A user-level/global cache directory (e.g. `~/.cache/p2c/`) — rejected in
  favor of keeping caching run-scoped under `<output>/.p2c/`, consistent
  with how every other piece of run state already lives.
- Deduplicating `WebSearch` calls, or any cross-topic search-query
  coordination — only the fetch step is shared; searches stay independent.
- Batching multiple topics/modules into a single researcher/writer agent
  call to reduce total agent count — a different, independent lever
  (reducing fan-out itself, rather than caching), not pursued in this design
  per the decision to focus specifically on re-run cost and redundant
  source fetching.
- Any reduction of per-call context size sent to existing agents — a
  separate prompt-trimming concern, not part of either caching mechanism.
