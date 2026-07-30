---
name: presentation2course
description: Use when the user wants a lecture slide deck (PDF or PPTX), or a folder of decks, turned into a course they can actually study from — "turn this deck into a course", "make a course from these lectures", "I can't revise from these slides". Produces a self-contained course.html with analogies, diagrams, a glossary and per-topic quizzes, plus course.pdf.
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

Confirm the one runtime dependency:

```bash
python3 -c "import markdown" 2>/dev/null || echo MISSING
```

If it prints `MISSING`, install it and continue:

```bash
python3 -m pip install --user markdown || {
  python3 -m venv "$HOME/.p2c-venv" && "$HOME/.p2c-venv/bin/pip" install markdown
}
```

If the venv fallback was used, run every `python3`/script invocation below with
`$HOME/.p2c-venv/bin/python3` instead.

The run layout, all of it on disk so the loop is restartable and each phase is
independently testable:

```
<output>/
  course.html                   deliverable
  course.pdf                    deliverable (skipped if Chromium absent)
  course.md                     source of truth
  KNOWN-ISSUES.md               only if blocking findings survive pass 3
  .p2c/
    normalized/*.pdf
    outline.json
    research/<topic-id>.md
    modules/<nn>-<slug>.md
    review/pass-<n>.json
```

## Phase 0 — normalize (script, no agent)

```bash
"<SKILL>/scripts/normalize" <input> --out "<output>/.p2c/normalized"
```

Read the JSON on stdout for `pdfs`, `converted`, `pages`, `total_pages`.

- **exit 4** — PPTX input with no LibreOffice. **Stop the run.** Print the install command
  from stderr verbatim. Do not fall back to text extraction: it would silently discard
  every diagram, and the diagram is usually the most valuable thing on the slide.
- **exit 5** — an unreadable or zero-page deck. **Stop the run**, printing the offending
  file from stderr.

## Phase 1 — summarizer (1 agent)

Dispatch one subagent with `<SKILL>/references/agents/summarizer.md` as its instructions,
plus the paths of the normalized PDFs and the output path
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

For every module, dispatch one subagent with
`<SKILL>/references/agents/course-writer.md`, giving it:

- its module object, with its topics in order,
- the contents of `<output>/.p2c/research/<topic-id>.md` for each of its topics,
- the paths `<SKILL>/references/style-guide.md` and `<SKILL>/references/quiz-format.md`,
- its output path `<output>/.p2c/modules/<nn>-<slug>.md`.

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

- **exit 0** — clean. Continue to Phase 5.
- **exit 3** — blocking validation findings. `course.html` still exists. Read the
  `blocking` array from stdout (also written to `<output>/.p2c/review/build-findings.json`)
  and re-dispatch **only** the responsible units, using each finding's `route`, `module`
  and `topic`:
  - `route: "writer"` → that one module's course-writer, given the findings for its module.
  - `route: "researcher"` → that one topic's researcher.
  - `route: "summarizer"` → the summarizer, to extend its gap list, then that topic forward.
  - `route: "build"` → no agent; fix the input and re-run the build.
  Then re-run the build. A malformed mermaid block gets exactly **one** repair attempt from
  its writer; after that the writer must replace it with a prose description, because a
  broken diagram never ships.
- **exit 1** — a missing module file or invalid outline. Read stderr; if a writer never
  wrote its file, re-dispatch that one writer.

Re-rendering is free, which is what makes three passes affordable.

## Phase 5 — review panel (2 agents, in parallel), then the loop

For pass `n` (starting at 1), dispatch both reviewers in parallel:

- **novice-simulator** — `<SKILL>/references/agents/novice-simulator.md`. Give it
  **only** `<output>/course.html` and its output path
  `<output>/.p2c/review/pass-<n>.json`. Never the decks, never the research, never the
  outline. A reviewer that has seen the upstream context cannot un-see it and will read a
  confusing sentence as clear because it knows what was meant. Its decisive instruction is
  *attempt every quiz using only what the course itself taught you*.
- **rubric-auditor** — `<SKILL>/references/agents/rubric-auditor.md`. Give it
  `course.html`, `outline.json`, the normalized decks, and the research files. Its output
  path is `<output>/.p2c/review/pass-<n>-auditor.json`.

Validate each file before acting on it:

```bash
PYTHONPATH="<SKILL>/scripts" python3 -m p2c.review check "<output>/.p2c/review/pass-<n>.json"
PYTHONPATH="<SKILL>/scripts" python3 -m p2c.review check "<output>/.p2c/review/pass-<n>-auditor.json"
```

Then apply the guards:

1. Collect both reviewers' findings. `blocking` and `route` come from the code, never from
   the reviewer.
2. Drop any finding already in the seen set — that is the **oscillation guard**. A finding
   that reappears after being marked fixed is recorded, not re-fixed.
3. If there are **no new blocking findings**, exit the loop early.
4. Otherwise re-dispatch only the routed units (same routing table as Phase 4), re-run the
   build, and start pass `n + 1`.
5. Stop unconditionally after **three passes**. This is a hard cap: "until it's good" never
   terminates, because a reviewer can always find something.

Noted findings are recorded and never cost a pass.

If blocking findings survive pass 3, write `KNOWN-ISSUES.md` and ship anyway:

```bash
PYTHONPATH="<SKILL>/scripts" python3 -m p2c.review known-issues \
  "<output>/.p2c/review/pass-3.json" "<output>/.p2c/review/pass-3-auditor.json" \
  --title "<course title>" --out "<output>/KNOWN-ISSUES.md"
```

Silently shipping a course with weak sections is the one outcome this design makes
impossible: the student needs to know which parts to distrust.

## Phase 6 — export the PDF (script, once)

Run this **once**, only after the loop has converged — never inside it. Each Chromium run
is expensive and produces nothing of value while the content is still in flux.

```bash
"<SKILL>/scripts/export-pdf" --html "<output>/course.html" --out "<output>/course.pdf"
```

- **exit 0** — done; the JSON reports the page count.
- **exit 6** — no Chromium. Skip it and say so, pointing the user at the in-page Download
  PDF button. Unlike missing LibreOffice, the cost here is one user click, not lost content.

## Final report

Report all of it at once, at the end:

```
Course: <title>  (<n> modules, <n> topics, <n> quizzes, theme <name>)
Written:  <output>/course.html
          <output>/course.pdf        (or: skipped — no Chromium; use the Download PDF button)
          <output>/course.md
Review:   <n> passes, <n> blocking findings resolved, <n> noted findings recorded
Unverified topics: <ids, or none>
Known issues: <output>/KNOWN-ISSUES.md  (only if it was written)
Agents run: <n>
```

## Failure handling

| Condition | Behaviour |
|---|---|
| `soffice` missing, PPTX input | Hard fail (`normalize` exit 4), print the install command |
| Chromium missing | Skip `course.pdf` (`export-pdf` exit 6), note it, HTML print button still works |
| Deck pages unreadable or blank | Hard fail (`normalize` exit 5, or the summarizer's report) with the page refs |
| Research unsubstantiated | Mark the topic `unverified`, the writer hedges, never invents |
| Mermaid unparseable | One repair attempt from its writer, then a prose description |
| Blocking findings after pass 3 | Ship with `KNOWN-ISSUES.md` |
| A subagent produces no file | Re-dispatch that one agent once, then stop and report it |
