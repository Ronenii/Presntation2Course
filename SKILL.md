---
name: presentation2course
description: Use when the user wants a lecture slide deck (PDF or PPTX), an article/essay/research paper (PDF, DOCX, TXT, or MD), or a folder of any of these, turned into a course they can actually study from — "turn this deck into a course", "make a course from these lectures", "turn this paper into a course", "I can't revise from these slides". Produces a self-contained <course-title>.html with analogies, diagrams, a glossary and per-topic quizzes, plus a matching <course-title>.pdf.
---

# Presentation2Course

Turns a lecturer's terse deck into the course the lecturer delivered out loud: plain
framing, an analogy before the jargon, a diagram, a worked example, and a comprehension
check after every topic.

**Ask the user no questions during a run.** They did not write the deck and have no
context to contribute. Everything — outputs, skips, unverified topics, known issues — is
reported at the end.

**Never fabricate.** If research cannot substantiate a topic it is marked `unverified` and
the writer hedges. A student who cannot tell the difference is worse off with invention
than with an admitted gap.

## 0. Setup and paths

`<SKILL>` is this skill's directory. Resolve the run's paths first:

- `<input>`: the file or directory the user named.
- `<output>`: `./<stem>-course/` in the current working directory, where `<stem>` is the
  input's filename without extension (single file) or its directory name (folder). If the
  user named an output directory, use theirs.
- `<basename>`: the deliverables' shared stem — slugified from outline.json's own
  `slug` field, a short English identifier the summarizer writes deliberately
  (the same way module/topic `id`s are always ASCII regardless of the course's
  `language`). Never derived from `title` — a non-Latin title transliterated
  phonetically would be unreadable, not translated. The build script (below)
  computes and reports this; do not derive it yourself — its JSON summary's
  `course_html`/`course_md` fields are the literal paths to use for every later phase.
- `<language>`: the target language for this course. **Required — the user must
  state it explicitly every time; there is no default.** Resolve whatever they said
  (a name, a demonym, an ISO code, "in Hebrew") to its English name and ISO 639-1
  code, e.g. `{"name": "Hebrew", "code": "he"}`. If the request states no language
  at all, or states something you cannot confidently resolve to a real language,
  **hard fail before Phase 0 begins** and print the exact wording you could not
  resolve. This is never a question to ask — the zero-questions rule holds even
  here, because a wrong guess means redoing the entire run in the wrong language.

Confirm the runtime dependencies:

```bash
python3 -c "import markdown, pypdfium2, PIL; assert markdown.__version_info__ >= (3, 5)" 2>/dev/null || echo MISSING
```

If it prints `MISSING`, install everything the build needs and continue:

```bash
python3 -m pip install --user -r "<SKILL>/requirements.txt" || {
  python3 -m venv "$HOME/.p2c-venv" && "$HOME/.p2c-venv/bin/pip" install -r "<SKILL>/requirements.txt"
}
```

If the venv fallback was used, run every `python3`/script invocation below with
`$HOME/.p2c-venv/bin/python3` instead.

The run layout, all of it on disk so the loop is restartable and each phase is
independently testable:

```
<output>/
  <basename>.html                deliverable
  <basename>.pdf                 deliverable (skipped if Chromium absent)
  <basename>.md                  source of truth
  KNOWN-ISSUES.md               only if blocking findings survive pass 3
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

## Phase 0 — normalize (script, no agent)

```bash
"<SKILL>/scripts/normalize" <input> --out "<output>/.p2c/normalized"
```

Read the JSON on stdout for `pdfs`, `converted`, `pages`, `total_pages`.

- **exit 4** — PPTX or DOCX input with no LibreOffice. **Stop the run.** Print the install
  command from stderr verbatim. Do not fall back to text extraction: it would silently
  discard every diagram, and the diagram is usually the most valuable thing on the slide.
- **exit 5** — an unreadable or zero-page deck. **Stop the run**, printing the offending
  file from stderr.
- **exit 7** — TXT or MD input with no headless Chromium available. **Stop the run.** Print
  the install command from stderr verbatim. Unlike PDF export's own Chromium dependency
  (which skips softly, since the HTML course still has a working print button), there is no
  fallback here: without Chromium there is no way to turn plain text into the page images
  the summarizer reads.

On a clean exit, check the cross-run cache before spending Phase 1/2:

```bash
"<SKILL>/scripts/cache" check --normalized "<output>/.p2c/normalized" --cache-root "<output>/.p2c/cache"
```

- **hit** — copy `outline` to `<output>/.p2c/outline.json` and every file
  under `research_dir` to `<output>/.p2c/research/`, then run the same
  `planned_agent_count` report the summarizer's phase would print on a real
  run (the user should still see the fan-out that's about to happen in the
  course-writer's phase, even though the summarizer/researcher phases were
  skipped) and go straight to the course-writer's phase below.
- **miss** — continue to the summarizer's phase below as normal. After the
  researcher's phase completes (all research files written), before the
  course-writer's phase begins, run:

  ```bash
  "<SKILL>/scripts/cache" store --normalized "<output>/.p2c/normalized" --cache-root "<output>/.p2c/cache" --outline "<output>/.p2c/outline.json" --research "<output>/.p2c/research"
  ```

  A cache write is an optimization only — its outcome does not change how
  the run proceeds. Continue to the course-writer's phase regardless of
  whether `stored` is `true` or `false`.

## Phase 1 — summarizer (1 agent)

Dispatch one subagent with `<SKILL>/references/agents/summarizer.md` as its instructions,
plus the paths of the normalized PDFs, the resolved `<language>`, and the output path
`<output>/.p2c/outline.json`. It reads pages **visually, in batches of 20** — never by text
extraction.

When it finishes, validate and report the planned fan-out before spending it:

```bash
PYTHONPATH="<SKILL>/scripts" python3 -c "
from pathlib import Path
from p2c.outline import load_outline, planned_agent_count, topic_ids
o = load_outline(Path('<output>/.p2c/outline.json'))
print(f\"{o['title']}: {len(o['modules'])} modules, {len(topic_ids(o))} topics\")
print(f'planned_agent_count: {planned_agent_count(o)}')
"
```

Print that agent count to the user before Phase 2 so a runaway fan-out on a whole semester
of decks is visible in the transcript rather than discovered from the bill. If the
validator raises, send the errors back to the summarizer once; if it fails again, stop.

If the summarizer reports blank or unreadable pages, stop the run and print the page refs.

## Phase 2 — researcher (one agent per topic, in parallel)

For every topic in `outline.json`, dispatch one subagent with
`<SKILL>/references/agents/researcher.md`, giving it:

- the topic object verbatim, including its `gaps`, `jargon` and `diagrams`,
- the titles of the immediately neighbouring topics for context,
- its output path `<output>/.p2c/research/<topic-id>.md`.

Send them all in one message so they run in parallel. Do not give a researcher the whole
outline — it invites drift into neighbours' topics.

When they finish, record which topics could not be substantiated; the final report names
them, and their writers must hedge rather than invent:

```bash
grep -l "^unverified: true" "<output>"/.p2c/research/*.md || echo "none"
```

## Phase 3 — course-writer (one agent per module, in parallel)

Before dispatching, compute every module's exact output filename yourself — never ask a
writer to derive its own. `p2c.assemble.module_filename` (what `scripts/build` actually
uses to find each file) slugifies the module title, and `p2c.text.slugify` ASCII-folds its
input; a non-Latin-script title (Hebrew, Arabic, ...) folds to nothing and falls back to
the literal string `"section"`. A writer following a "lowercase and hyphenate the title"
rule would produce something else entirely, and the build would then raise
`AssembleError: module file not written` because it looked for the real, computed name and
found none. Compute the real names up front instead:

```bash
PYTHONPATH="<SKILL>/scripts" python3 -c "
from pathlib import Path
from p2c.outline import load_outline
from p2c.assemble import module_filename
o = load_outline(Path('<output>/.p2c/outline.json'))
for i, m in enumerate(o['modules'], 1):
    print(f\"{m['id']}: {module_filename(i, m)}\")
"
```

For every module, dispatch one subagent with
`<SKILL>/references/agents/course-writer.md`, giving it:

- its module object, with its topics in order,
- the resolved `<language>`, so its prose, analogies, and quizzes are written in it
  (jargon terms stay in their original form — see `course-writer.md`),
- each topic's `reusable_image`, if it set one, flows through automatically
  since topic objects are passed verbatim — no separate step needed here,
  but the writer must be told about it via the dispatch text, not left to
  notice it buried in the JSON.
- each topic's `depth` also flows through automatically since topic objects are passed
  verbatim, but — same as `reusable_image` — the writer must be told what it means via
  the dispatch text (see `references/agents/course-writer.md` and
  `references/style-guide.md`'s "Brief topics" section), not left to infer it from the
  bare string.
- the contents of `<output>/.p2c/research/<topic-id>.md` for each of its topics,
- the paths `<SKILL>/references/style-guide.md` and `<SKILL>/references/quiz-format.md`,
- its literal, exact output path — `<output>/.p2c/modules/<the-computed-filename>` from
  the command above, handed to it directly, not a description of how to derive one.

One agent per module, all in parallel. The writer writes each topic's quizzes while that
topic is in its hands, which is why questions do not drift from the prose that taught them.

## Phase 4 — build (script, no agent)

```bash
"<SKILL>/scripts/build" \
  --outline "<output>/.p2c/outline.json" \
  --modules "<output>/.p2c/modules" \
  --out "<output>" \
  --assets "<SKILL>/assets"
```

Read `course_html`/`course_md` from its JSON stdout — these are the literal
`<output>/<basename>.html`/`.md` paths every later phase must use; never re-derive
`<basename>` yourself.

- **exit 0** — clean. Continue to Phase 5.
- **exit 3** — blocking validation findings. `<basename>.html` still exists. Read the
  `blocking` array from stdout (also written to `<output>/.p2c/review/build-findings.json`)
  and re-dispatch **only** the responsible units, using each finding's `route`, `module`
  and `topic`:
  - `route: "writer"` → that one module's course-writer, given the findings for its module.
  - `route: "researcher"` → that one topic's researcher.
  - `route: "summarizer"` → the summarizer, to extend its gap list, then that topic forward.
  - `route: "build"` → no agent by default; fix the input and re-run the build. But if the
    finding's underlying content was itself written by an agent, rather than being a
    structural/template defect with no corresponding agent at all, re-dispatch that
    content's owning agent instead of treating it as un-fixable script-only work: for
    example `glossary_malformed` traces to a course-writer's malformed glossary block, not
    to the build script, so it re-dispatches that module's course-writer — the same
    "writer" case above — because re-running the build without changing the input
    reproduces the identical finding forever.
  Then re-run the build. A malformed mermaid block gets exactly **one** repair attempt from
  its writer; after that the writer must replace it with a prose description, because a
  broken diagram never ships.
- **exit 1** — a missing module file, an invalid outline, or an unresolvable `figure`
  source. Read stderr; if a writer never wrote its file — including if it wrote to a
  filename it derived itself instead of the literal path it was given, which is the same
  failure mode Phase 3's up-front filename computation exists to prevent — re-dispatch
  that one writer with its exact output path restated. If stderr instead names a `figure`
  block whose `reusable_image` slide reference does not exist in the normalized deck, or
  is out of page range, the bad value traces back to the summarizer, not the build: fix
  or re-dispatch the summarizer to correct that topic's `reusable_image` against the
  actual deck, then re-dispatch that topic's writer forward with the corrected value.

Cap build-repair at **two** rounds — mirroring Phase 5's pass cap, but shorter, because
re-rendering is cheap and this phase exists to catch narrow mechanical issues, not
open-ended content problems: a defect a writer won't fix in two rounds needs the fuller
review loop, not a third build round. If blocking findings are still open after two repair
rounds, do not loop Phase 4 a third time — carry those findings forward into Phase 5's
review-loop finding set, where they get the same seen/oscillation tracking as any
reviewer finding and, if they survive that loop too, the same `KNOWN-ISSUES.md`
disclosure path.

Re-rendering is free, which is what makes two build-repair rounds and three review passes
affordable.

## Phase 5 — review panel (2 agents, in parallel), then the loop

For pass `n` (starting at 1), dispatch both reviewers in parallel:

- **novice-simulator** — `<SKILL>/references/agents/novice-simulator.md`. Give it
  **only** the built course HTML (Phase 4's reported `course_html` path) and its output path
  `<output>/.p2c/review/pass-<n>.json`. Never the decks, never the research, never the
  outline. A reviewer that has seen the upstream context cannot un-see it and will read a
  confusing sentence as clear because it knows what was meant. Its decisive instruction is
  *attempt every quiz using only what the course itself taught you*.
- **rubric-auditor** — `<SKILL>/references/agents/rubric-auditor.md`. Give it
  the built course HTML, `outline.json`, the normalized decks, and the research files. Its
  output path is `<output>/.p2c/review/pass-<n>-auditor.json`.

Validate each file before acting on it:

```bash
PYTHONPATH="<SKILL>/scripts" python3 -m p2c.review check "<output>/.p2c/review/pass-<n>.json"
PYTHONPATH="<SKILL>/scripts" python3 -m p2c.review check "<output>/.p2c/review/pass-<n>-auditor.json"
```

Then apply the guards:

1. Collect both reviewers' findings for pass `n`. `blocking` and `route` come from the
   code, never from the reviewer. Keep the **full** blocking-findings list for this pass —
   call it `blocking_n`, every blocking finding from both `pass-<n>.json` and
   `pass-<n>-auditor.json`, regardless of whether it is new — separately from the *new*
   subset the next guard computes. `blocking_n` is what guard 3's exit and guard 5's cap
   check for disclosure below; it is never itself filtered by the oscillation guard.
2. From `blocking_n`, drop any finding already in the seen set to get this pass's *new*
   blocking findings — that is the **oscillation guard**. A finding that reappears after
   being marked fixed is recorded, not re-fixed, and does not by itself force another pass.
3. If there are **no new blocking findings**, exit the loop after this pass.
4. Otherwise re-dispatch only the routed units (same routing table as Phase 4), re-run the
   build, and start pass `n + 1`.
5. Stop unconditionally after **three passes**. This is a hard cap: "until it's good" never
   terminates, because a reviewer can always find something.

Noted findings are recorded and never cost a pass.

Whichever guard actually stops the loop — the early exit at guard 3, or the hard cap at
guard 5 — check `blocking_n` for the pass the loop stopped at, not the new-since-seen delta
guard 2 computed: a finding recorded in an earlier pass, marked fixed, and reappearing in
this pass is dropped by guard 2 (it is not "new") but still belongs in `blocking_n`, so it
must still trigger disclosure even though it did not trigger another pass. If `blocking_n`
is non-empty, write `KNOWN-ISSUES.md` from **that pass's** two files and ship anyway:

```bash
PYTHONPATH="<SKILL>/scripts" python3 -m p2c.review known-issues \
  "<output>/.p2c/review/pass-<n>.json" "<output>/.p2c/review/pass-<n>-auditor.json" \
  --title "<course title>" --out "<output>/KNOWN-ISSUES.md"
```

where `<n>` is whichever pass the loop actually stopped at — not necessarily pass 3, since
guard 3 can exit the loop as early as pass 1.

Silently shipping a course with weak sections is the one outcome this design makes
impossible: the student needs to know which parts to distrust.

## Phase 6 — export the PDF (script, once)

Run this **once**, only after the loop has converged — never inside it. Each Chromium run
is expensive and produces nothing of value while the content is still in flux.

```bash
"<SKILL>/scripts/export-pdf" --html "<output>/<basename>.html" --out "<output>/<basename>.pdf"
```

(`<basename>` here is the literal value Phase 4 reported — never re-derived.)

- **exit 0** — done; the JSON reports the page count.
- **exit 6** — no Chromium. Skip it and say so, pointing the user at the in-page Download
  PDF button. Unlike missing LibreOffice, the cost here is one user click, not lost content.

## Final report

Report all of it at once, at the end:

```
Course: <title>  (<n> modules, <n> topics, <n> quizzes, theme <name>)
Written:  <output>/<basename>.html
          <output>/<basename>.pdf     (or: skipped — no Chromium; use the Download PDF button)
          <output>/<basename>.md
Review:   <n> passes, <n> blocking findings resolved, <n> noted findings recorded
Unverified topics: <ids, or none>
Known issues: <output>/KNOWN-ISSUES.md  (only if it was written)
Agents run: <n>
```

## Failure handling

| Condition | Behaviour |
|---|---|
| `soffice` missing, PPTX or DOCX input | Hard fail (`normalize` exit 4), print the install command |
| Chromium missing, PDF export | Skip `<basename>.pdf` (`export-pdf` exit 6), note it, HTML print button still works |
| Chromium missing, TXT/MD input | Hard fail (`normalize` exit 7), print the install command — no fallback exists for this input type |
| No language stated, or unresolvable | Hard fail before Phase 0, print the offending wording |
| Deck pages unreadable or blank | Hard fail (`normalize` exit 5, or the summarizer's report) with the page refs |
| Research unsubstantiated | Mark the topic `unverified`, the writer hedges, never invents |
| Mermaid unparseable | One repair attempt from its writer, then a prose description |
| Blocking findings after pass 3 | Ship with `KNOWN-ISSUES.md` |
| A course-writer's file isn't where the build expects it (exit 1) | Re-dispatch that one writer with its exact path restated |
| A `figure` block's `reusable_image` slide ref doesn't exist or is out of range (exit 1) | Re-dispatch the summarizer to correct the slide ref against the actual deck, then that topic's writer |
| A subagent produces no file | Re-dispatch that one agent once, then stop and report it |
