# Presentation2Course — Design

**Date:** 2026-07-28
**Status:** Approved

## Problem

Lecturers build slide decks as prompts for themselves, not as teaching material. The
result is dense with technical jargon, light on background, and close to useless to a
student revising alone. The deck states conclusions the lecture explained out loud.

This skill turns such a deck into a course a student can learn from unaided:
descriptive prose, analogies before jargon, visualizations, and a comprehension check
after every topic.

## Scope

**In:** PDF and PPTX input, single deck or a folder of decks, HTML + PDF output,
web-assisted research, per-topic multiple-choice quizzes, a bounded self-review loop.

**Out:** video, audio, LMS export, multi-language, student accounts, progress
persistence across sessions, editing the source deck.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Input unit | Single file *or* directory, auto-detected | Courses span lectures; students hold one deck at a time |
| Ingestion | Normalize everything to PDF, read pages visually | Slide diagrams carry meaning that text extraction destroys |
| Research | WebSearch/WebFetch + model knowledge | Terse decks are often niche; model knowledge alone risks confident invention |
| Quizzes | Inline MCQ after every topic, ungraded, immediate correct/incorrect + explanation | Checks land while the concept is fresh; no scoring means no state to corrupt |
| Output | Self-contained `course.html` + `course.pdf`, from `course.md` | Portable, offline, interactive, no toolchain for the student |
| Design | Shipped as versioned assets, 3 theme variants | Authoring CSS at runtime is a per-run quality gamble that can never be improved |
| Build | Deterministic script, not an agent | Mechanical work with a right answer; makes review iterations free |
| Review loop | Rubric + hard cap of 3 passes | "Until good" never terminates; reviewers always find something |
| User interaction | Zero questions during a run | The student did not write the deck and has no context to contribute |

### Rejected alternatives

- **Static-site generator output** — adds a toolchain a student should not need.
- **Claude artifact URL as the deliverable** — ties the course to a hosted service.
- **A `designer` agent authoring a bespoke theme per course** — quality varies run to
  run, creates a designer/implementer integration seam, and diverts the reviewer into
  litigating design taste instead of pedagogy.
- **A separate quiz-author agent** — with inline per-topic quizzes it must re-read and
  re-infer what the topic taught, so questions drift from the prose. The course-writer
  writes each topic's quizzes while that topic is in its hands.
- **Single agent, no subagents** — cannot hold a semester of decks in context, gets no
  parallelism, and cannot credibly novice-review its own writing.
- **Text-only extraction** — silently discards every diagram, chart, and visual
  relationship on the slides.

## Repository layout

This repository *is* the skill. Installation is a copy or symlink into
`.claude/skills/`.

```
SKILL.md                        orchestrator
README.md
references/
  rubric.md                     blocking vs noted findings
  style-guide.md                topic rhythm, tone, analogy rules
  quiz-format.md                fenced block grammar
  outline-schema.json           summarizer output contract
assets/
  themes/<name>/
    template.html
    theme.css
    course.js
  print.css                     shared print layout
  vendor/mermaid.min.js         vendored, zero external requests
scripts/
  normalize                     PPTX/PDF -> normalized PDFs
  build                         course.md -> course.html, validate
  export-pdf                    course.html -> course.pdf
tests/
  fixtures/                     terse sample PPTX + PDF
  broken-course/                deliberately defective course, for reviewer tests
```

## Run artifacts

Every handoff between phases is a file on disk. Nothing important lives only in an
agent's context. This is what makes the loop restartable and each phase independently
testable.

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

## Pipeline

### Phase 0 — normalize (script)

PDFs copy through. PPTX converts via `soffice --headless --convert-to pdf`.

When the input includes PPTX and `soffice` is absent, this is a **hard failure** with
the install command. Degrading to text extraction would silently discard every diagram,
and a silent loss of the most valuable content on the slides is not an acceptable
outcome. PDF-only input does not require LibreOffice at all.

### Phase 1 — summarizer (1 agent)

Reads normalized pages visually, in batches of 20. Emits `outline.json`:

```json
{
  "title": "string",
  "subject_domain": "systems | theory | life-sciences | other",
  "source_decks": ["string"],
  "modules": [{
    "id": "string",
    "title": "string",
    "prerequisites": ["string"],
    "topics": [{
      "id": "string",
      "title": "string",
      "slide_refs": ["deck.pdf#12"],
      "jargon": ["string"],
      "diagrams": ["prose description of what the slide's diagram shows"],
      "gaps": ["asserted by the deck but never explained"]
    }]
  }]
}
```

`gaps` is the researcher's work order. It is the field that converts a lecturer's
shorthand into a course, and the summarizer is instructed to be aggressive about
populating it — anything a first-time reader could not derive from the slide alone.

`subject_domain` drives theme selection and nothing else.

### Phase 2 — researcher (one agent per topic, parallel)

Input: the topic entry, its `gaps`, and its immediate neighbours for context.
Output: `research/<topic-id>.md` containing plain-language definition, why it matters,
one or two candidate analogies, one worked example, common misconceptions, a spec for
the visualization the topic needs, and sources with URLs.

If research cannot substantiate a topic, it is marked `unverified: true`. The writer is
then required to hedge. **Fabricating a confident explanation is never permitted** — a
student who cannot tell the difference is worse off with invention than with an
admitted gap.

### Phase 3 — course-writer (one agent per module, parallel)

Input: the module's topics, their research, `references/style-guide.md`.
Output: `modules/<nn>-<slug>.md`.

Each topic follows a fixed rhythm: plain-language framing → analogy → technical
content → visual → worked example → quiz. **The analogy precedes the jargon.** That
ordering is the point of the project.

### Phase 4 — build (script, no agent)

1. Concatenate modules into `course.md` with front matter.
2. Select theme from `subject_domain` via the mapping table.
3. Render into the theme template.
4. Validate. Failures route to the responsible module only.

`export-pdf` runs **once, after the review loop converges** — not on every build. The
loop may re-render several times, and each Chromium run is expensive with nothing to
show for it while the content is still in flux.

Validations: every quiz block well-formed; every mermaid block parses; no unresolved
placeholders; every `outline.json` topic present; every jargon term has a glossary
entry; no external requests in the HTML.

### Phase 5 — review panel (2 agents, parallel)

**novice-simulator** sees only `course.html`. Never the deck, never the research. A
reviewer that has seen the upstream context cannot un-see it and will read a confusing
sentence as clear because it knows what was meant. Deliberate ignorance is the value.

Its decisive instruction: *attempt every quiz using only what the course itself taught
you.* A question answerable only from outside knowledge is a blocking finding. This
makes comprehensibility a test with a pass/fail answer rather than a matter of taste.

**rubric-auditor** sees the artifact, `outline.json`, and the normalized decks. Checks
fidelity: nothing invented, nothing important dropped, jargon coverage, citation
traceability.

## Content formats

### Quiz block

````
```quiz
q: What does a TLB actually cache?
- [ ] The contents of recently used pages
- [x] Virtual-to-physical page mappings
- [ ] The page table itself
why: It caches translations, not data. Confusing it with a data cache is
     the most common mistake here — the TLB sits in front of the page
     table, not in front of memory.
```
````

Grammar: one `q:` line; 3–4 options; exactly one `[x]`; non-empty `why:`.

The style guide requires `why:` to address the *tempting* wrong answer, not restate the
right one. That is where the teaching happens.

One or more quiz blocks per topic. Ungraded. Unlimited retries.

### Visualizations

Mermaid for anything expressible as flow, sequence, state, or architecture; inline SVG
otherwise. Mermaid is vendored so the HTML makes zero external requests.

Mermaid renders client-side, so `export-pdf` must wait for render-complete before
printing or the PDF contains empty boxes.

A mermaid block that fails to parse gets one repair attempt from its writer, then
degrades to a text description. A broken diagram never ships.

### Glossary

Every jargon term the summarizer captured becomes an underlined term with a
click-to-reveal definition, plus a full glossary appendix. This attacks the stated
problem — jargon without background — most directly, and is nearly free given the
summarizer already collects the terms.

## HTML behaviour

Stateless. No scores means no `localStorage`, which means no stale-state bugs.

Sticky sidebar TOC with current-section highlight; click a quiz option for immediate
correct/incorrect plus explanation, unlimited retries; prerequisite callouts at module
start; analogy callouts styled distinctly from technical content; light/dark; Download
PDF button triggering the browser print dialog.

## Themes

Varies: type pairing, accent palette, diagram colours.
Fixed: layout, spacing scale, component structure — so a theme can never break a build.

| `subject_domain` | Theme |
|---|---|
| `systems` | `slate` — cool neutrals, mono accents |
| `theory` | `parchment` — warm neutrals, serif headings |
| `life-sciences` | `clinical` — high-key whites, teal accents |
| `other` | `slate` (default) |

## PDF output

One layout definition, two outputs, so the PDF can never drift from the HTML.

`assets/print.css` defines print layout and serves both paths:

- `course.html` ships a Download PDF button invoking the browser print dialog. Zero
  dependencies, always available.
- `scripts/export-pdf` runs headless Chromium against the rendered HTML to emit
  `course.pdf`.

Missing Chromium degrades gracefully — skip with a note pointing at the in-page button.
Unlike missing LibreOffice, the cost is one user click, not lost content.

In the PDF, each quiz question is immediately followed by its correct answer and
explanation.

## Review loop

### Blocking findings (trigger a re-run)

- A jargon term used before it is defined, or never defined.
- A topic with no quiz.
- A quiz question answerable only from outside knowledge.
- A claim traceable to neither the deck nor a cited source.
- A topic in `outline.json` missing from the course.
- An analogy that breaks down in a way that teaches something false.

### Noted findings (recorded, never looped)

Verbosity, style, nice-to-have visuals. Without this split the loop cannot terminate,
because there is always something a reviewer could improve.

### Routing

| Finding | Re-runs |
|---|---|
| Missing or wrong background | that one researcher |
| Unclear prose, weak analogy, bad quiz | that one module's writer |
| Topic missing entirely | summarizer gap list, then that topic forward |
| Render or validation failure | build script, no agent |

Only the affected unit re-runs. Re-rendering is free, which is what makes three passes
affordable.

### Convergence guards

1. Hard cap of 3 passes.
2. Early exit when a pass produces no new blocking findings.
3. Oscillation guard — a finding that reappears after being marked fixed is recorded,
   not re-fixed.

If blocking findings survive pass 3, ship the course **plus `KNOWN-ISSUES.md`** listing
them. Silently shipping a course with weak sections is the one outcome the design makes
impossible; the student needs to know which parts to distrust.

## Failure handling

| Condition | Behaviour |
|---|---|
| `soffice` missing, PPTX input | Hard fail, print install command |
| Chromium missing | Skip `course.pdf`, note it, HTML print button still works |
| Deck pages unreadable or blank | Hard fail with the offending page refs |
| Research unsubstantiated | Mark topic `unverified`, writer hedges, never invents |
| Mermaid unparseable | One repair attempt, then text description |
| Blocking findings after pass 3 | Ship with `KNOWN-ISSUES.md` |

All of it is reported at the end of the run: outputs written, steps skipped, known
issues, unverified topics.

## Testing

**Deterministic half — unit tested.** This is most of the risk surface.

- Quiz-block parsing: valid forms, and every malformed form (no `[x]`, two `[x]`,
  missing `why:`, 2 options, 5 options).
- Front matter, anchor generation, theme mapping.
- Golden-file snapshot of `course.md` → `course.html`.
- Fixture decks in `tests/fixtures/`: one terse PPTX, one terse PDF.

**Agent half — invariant tested.** Output is non-deterministic, so assert properties
rather than snapshots: every outline topic appears in the course; every topic has at
least one valid quiz; every jargon term has a glossary entry; no unresolved
placeholders; zero external requests in the HTML; PDF page count > 0.

**Reviewer regression test.** Run the novice-simulator against
`tests/broken-course/` — undefined jargon, a quiz requiring outside knowledge — and
assert it catches both. It is the highest-value agent in the pipeline, so "does the
reviewer work" should not be an article of faith.

## Open risks

- **Analogy quality is the hardest thing to verify mechanically.** A misleading analogy
  can pass every validator. The novice-simulator and the "breaks down in a way that
  teaches something false" rubric line are the only defences, and both are judgment.
- **Cost scales with topic count.** A semester of decks fans out to one researcher per
  topic. The orchestrator should report the planned agent count after Phase 1 so a
  runaway is visible in the transcript.
- **LibreOffice conversion fidelity** varies for animation-heavy or
  custom-font decks. Layout drift degrades the summarizer's visual read.
