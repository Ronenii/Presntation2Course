# Presentation2Course — Visual Engagement — Design

**Date:** 2026-07-30
**Status:** Approved

## Problem

Courses ship with inconsistent visual content. The style guide already mandates a visual
per topic (`references/style-guide.md`: "A `mermaid` diagram, or inline `<svg>`... skip it
only when the topic is genuinely non-spatial"), but nothing enforces it — a course-writer
can simply skip the step and no reviewer or check catches it reliably (the closest rubric
code, `missing_visual`, is explicitly non-blocking). Separately, every diagram today is a
Mermaid recreation the course-writer *guesses* at from the outline's prose description
(`diagrams: [...]` strings) — the writer never sees the deck's actual pixels, so the
recreation is necessarily lossy even when the slide itself already had a perfectly good
diagram or photo worth reusing verbatim. And courses have no mechanism for illustrating a
sequence or a before/after comparison other than static prose.

This design adds three things: a hard, deterministic gate for visual-per-topic coverage;
reuse of the actual slide image when it beats a redrawn guess; and a small, fixed library
of CSS animation patterns for sequence/comparison ideas.

## Scope

**In:** a deterministic coverage check (every topic has a visual or an explicit
justification); summarizer-flagged reuse of a slide's own image, extracted and embedded at
build time; a `figure` block type for reused images; an `animate` block type with exactly
two patterns (`step-reveal`, `state-toggle`); print-safe static rendering of both patterns.

**Out:** web-sourced or generated images (only images already present in the source deck
are ever reused — no network fetch, no generation, no licensing/attribution question to
solve); freeform per-topic animation authored ad hoc (only the two fixed patterns exist);
video, audio, or any other new media type (README's existing "What this won't do" already
excludes these); course-writer or researcher gaining the ability to view slide pixels
directly (only the summarizer does, unchanged from today).

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Who decides an image is worth reusing | The summarizer, at Phase 1 | It is the only agent that ever views slide pixels. Researcher and course-writer work from the outline's text description only, unchanged by this design — asking either to pick a crop region would mean guessing coordinates blind. |
| How much of the slide is reused | The whole page, not a cropped region | An agent has no reliable way to specify a precise bounding box for a slide it may not even be looking at (course-writer never sees pixels). Whole-page extraction is simple, deterministic, and delivers most of the value without new coordinate-guessing machinery. |
| At most how many reused images per topic | One | Keeps the schema, the dispatch, and the build-time substitution simple. A topic with multiple good images is expected to be rare; revisit only if it proves common. |
| Image rendering mechanism | `pypdfium2` (pure pip install, bundles its own binary) | No new system dependency (unlike poppler/`pdftoppm`), and doesn't require the already-optional headless Chromium to be present for a feature meant to work by default. |
| Where extraction happens | `build.py`, via a new `p2c.imagery` module | `build.py` already has filesystem access to the normalized PDFs and the outline; `mdrender.py` stays pure-text/side-effect-free, matching its existing contract. |
| Coverage enforcement mechanism | A new deterministic `p2c.invariants` check, not an LLM rubric code | Matches this project's existing preference for deterministic gates over agent judgment (RTL detection, module-filename derivation). The rubric-auditor's existing `missing_visual` code remains as a softer "is this visual any good" backstop, not the enforcement mechanism itself. |
| How a writer justifies skipping the visual step | An HTML comment, `<!-- no-visual: <reason> -->`, in the topic's markdown | Invisible to the student (comments are already stripped from rendered output, same as the existing `<!-- topic: id -->` markers), trivially greppable by both the invariants check and the rubric-auditor, and needs no new rendering machinery. |
| Animation pattern set | Exactly two: `step-reveal`, `state-toggle` | A bounded, reviewable library beats freeform per-topic animation authoring, which is high failure risk for both correctness (subtly broken CSS/SVG) and reviewability (a reviewer has no simple way to judge arbitrary animation code). |
| Animation in print | Static, all-states-shown rendering (a plain list for `step-reveal`, a labeled side-by-side for `state-toggle`) — not a frozen mid-animation frame | A frozen frame arbitrarily loses information the animation would have conveyed over time; showing every state at once in print keeps the full content, just without motion. |
| Do `figure`/`animate` blocks count toward the coverage gate | Yes, alongside `mermaid` and inline `<svg>` | All four are legitimate visual treatments; the gate cares about presence of *a* visual, not which kind. |

### Rejected alternatives

- **Course-writer picks a crop region from the outline's diagram description** — faster to
  imagine, but the writer never sees the deck's pixels, so any bounding box it names would
  be an unverifiable guess with no mechanism to check it against the real slide.
- **A dedicated new "image-scout" agent phase**, decoupled from the summarizer — cleaner
  separation of concerns, but disproportionate: the summarizer already reads every page
  batch, and adding a whole new phase (with its own dispatch, output contract, and failure
  handling) for a single optional field is more machinery than the feature is worth.
- **Freeform per-topic animation** authored however the course-writer judges best — more
  expressive, but an LLM authoring arbitrary animated SVG/CSS per topic is a well-known
  failure mode (subtly broken output, no simple way for a reviewer to judge quality or
  correctness), and directly contradicts the "moderate, helpful" bar this feature was
  scoped to.
- **Promote `missing_visual` to a blocking rubric code instead of a new invariants check**
  — simpler to state, but keeps enforcement as an LLM judgment call that costs a review
  pass to catch, instead of a free, instant, deterministic gate.
- **Freeze animations to their final frame for print** (the more common web pattern) —
  rejected because it silently drops whatever the earlier steps/states showed; a printed
  page that only ever shows one state that started as a several-step sequence is a worse
  document than the CSS-based alternative it replaced.

## Components changed

| File | Change |
|---|---|
| `references/outline-schema.json` | New optional `reusable_image` string per topic, same pattern as existing `slide_refs` items (`^.+#[0-9]+$`). |
| `scripts/p2c/outline.py` | Validate `reusable_image`'s shape when present. |
| `references/agents/summarizer.md` | Add: when and how to set `reusable_image` (at most one per topic, only when the slide's own diagram/photo is worth reusing verbatim rather than being redrawn). |
| `references/agents/course-writer.md` | Add: diagram-type selection guidance (flowchart / sequence / state / architecture); `figure` block syntax and rule to use it instead of authoring a visual when `reusable_image` was supplied in its dispatch; `animate` block syntax (`step-reveal`, `state-toggle`) and when it is warranted; the `<!-- no-visual: <reason> -->` escape hatch and when it is legitimate (genuinely non-spatial topics only). |
| `scripts/p2c/blocks.py` | Recognize `figure` and `animate` as extractable fence kinds. |
| `scripts/p2c/mdrender.py` | Render `figure` (parses `source:`/`caption:`, leaves an image-src placeholder token for build to resolve) and `animate` (parses `pattern:` plus its steps/states into the matching HTML structure). |
| `scripts/p2c/imagery.py` (new) | `extract_page_png(pdf_path: Path, page_number: int, dpi: int) -> bytes`, built on `pypdfium2`. |
| `scripts/p2c/build.py` | After rendering, resolve each `figure` placeholder to a base64 data URI by extracting the referenced page from `<output>/.p2c/normalized/<deck>.pdf`. Hard-fails with the offending topic and slide_ref if extraction fails. |
| `scripts/p2c/invariants.py` | New coverage check: every topic (scoped by its `<!-- topic: id -->` marker) contains a `mermaid`/`svg`/`figure`/`animate` visual or a `no-visual` comment; failing topics are named in the problem list. |
| `assets/base/layout.css` (or a new `assets/base/animations.css`, included the same way other theme assets are) | Keyframes for `step-reveal` and `state-toggle`, written with logical properties throughout (matching the existing RTL-safety convention), guarded by `prefers-reduced-motion: reduce`. |
| `assets/print.css` | Static, all-states-shown rendering for both animation patterns; no motion in print regardless of the reduced-motion setting. |
| `references/rubric.md` | Note that a reused `figure` or an `animate` block satisfies the same fidelity/coverage expectations as a `mermaid` diagram. |
| `requirements.txt` | Add `pypdfium2`. |
| `README.md` | Add `pypdfium2` to Requirements; the "only runtime dependency" claim for `markdown` no longer holds and is corrected. |

## Data flow

1. Phase 1 (summarizer) reads slide pages visually, as today, and may additionally set one
   `reusable_image: "<deck>#<page>"` per topic in `outline.json` when a slide's own visual
   is worth reusing verbatim.
2. Phase 3 (course-writer) dispatch includes that topic's `reusable_image` value when set.
   The writer then emits exactly one of: a `figure` block (caption only — the source
   ref is threaded through from its dispatch, not re-derived), an `animate` block, a normal
   `mermaid`/inline-`<svg>` visual, or — only for genuinely non-spatial topics — a
   `<!-- no-visual: <reason> -->` comment.
3. Phase 4 (build): `render_course()` renders all fences as today; any `figure` fence's
   image-src is left as a placeholder. `build.py` then resolves each placeholder by calling
   `p2c.imagery.extract_page_png()` against the matching file under
   `<output>/.p2c/normalized/`, embedding the result as a base64 data URI — the same
   self-contained-HTML pattern the vendored Mermaid bundle already uses.
4. Still in Phase 4 (or wherever `p2c.invariants` runs, both mid-loop and standalone): the
   new coverage check scans each topic's markdown between its `<!-- topic: id -->` markers
   for a visual fence or a `no-visual` comment, failing the build with the offending topic
   id(s) if neither is present.
5. Phase 5 review is unchanged in structure: rubric-auditor's existing `missing_visual` and
   diagram-fidelity checks now also apply to `figure`/`animate` content, evaluating quality
   rather than mere presence (presence is already guaranteed by step 4).

## Error handling

- `reusable_image` names a deck or page that doesn't exist, or `pypdfium2` fails to render
  it — hard build failure naming the offending topic id and slide_ref, matching this
  project's existing fail-fast style (bad deck, unresolvable language) rather than silently
  omitting the image.
- A topic with no visual and no `no-visual` comment — hard failure from the new
  `p2c.invariants` check, naming the topic id(s), before the course ever reaches review.
- A malformed `figure`/`animate` block (missing required fields, unbalanced structure) —
  falls through to the existing `render_failure` rubric code, same as a malformed `mermaid`
  block today.

## Testing

- `p2c.imagery` unit tests against a small fixture PDF (extract a known page, assert PNG
  dimensions/content at a fixed DPI).
- `p2c.invariants` tests for the new coverage check: a course where every topic has a
  visual (passes), a topic with none and no comment (fails, names the topic), a topic with
  only a `no-visual` comment (passes).
- Golden-snapshot additions: a `figure` block and an `animate` block added to the existing
  English golden fixture, and to the Hebrew golden fixture (reusing existing
  RTL-regression infrastructure), to lock in rendering and catch any logical-property
  regressions in the new CSS.
- A grep-based CSS check, parallel to the existing layout-CSS guard, asserting the new
  animation keyframes use only logical properties (no `left`/`right`/`margin-left` etc.).
- `requirements.txt`/install-time test confirming `pypdfium2` is declared and importable.
