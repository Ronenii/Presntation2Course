# Presentation2Course — Multi-Language Course Output — Design

**Date:** 2026-07-30
**Status:** Approved

## Problem

The skill only ever produces English courses today. A student whose deck — and whose
own study language — is Hebrew (or any other language) gets an English course
regardless. This removes the "No multi-language output" non-goal from the original
design and adds a general target-language parameter, with Hebrew as the first
supported language and the first right-to-left one.

## Scope

**In:** a required, per-invocation target-language parameter; every student-facing
artifact (prose, analogies, quizzes, glossary, `KNOWN-ISSUES.md`, the final report)
written in that language; correct right-to-left layout for RTL languages; jargon terms
kept in their original form inline even when their definitions are translated.

**Out:** auto-detecting the deck's own language and translating *from* it (research
and reasoning may still draw on English sources; only the course's own output language
changes); per-topic or mixed-language courses; a language switcher inside one generated
`course.html`; translating internal identifiers (topic ids, filenames, anchors — these
stay kebab-case/Latin, they are plumbing, never shown to the student).

## Decisions

| Decision | Choice | Why |
|---|---|---|
| How language is specified | Required, explicit, every invocation — no default | Silently defaulting to English (or guessing) risks generating an entire course in the wrong language, which is expensive to discover late and to redo |
| Unresolvable language | Hard-fail Phase 0, like a bad deck | Keeps `SKILL.md`'s "ask no questions" rule uniform instead of carving out a one-off exception |
| What gets translated | Everything student-facing | A course half in Hebrew and half in English (e.g. an English glossary) is a worse artifact than an all-English one — inconsistency reads as a bug |
| Jargon terms themselves | Kept in original form inline; only the *definition* is translated | Matches how Hebrew (and most) technical writing actually handles loanwords/acronyms; translating "TLB" itself would be actively confusing |
| Internal ids/filenames | Always Latin/kebab-case, regardless of course language | They are anchors and filenames the pipeline depends on being stable; the student never sees them |
| Reviewer findings (`pass-<n>.json`, `pass-<n>-auditor.json`) | Always English | Pipeline bookkeeping, not student-facing; keeps the orchestrator's own reasoning language-independent |
| RTL layout mechanism | Convert theme CSS to logical properties (`margin-inline-start`, `text-align: start`, ...) | One set of theme files serves both directions automatically; a duplicate `rtl.css` per theme would double the CSS surface and drift out of sync over time |
| Diagrams | Mermaid containers stay `dir="ltr"`-scoped regardless of page direction; labels are still translated | Diagram flow direction (arrows, top-down/left-right structure) is independent of prose direction; forcing RTL onto flowchart layout is not a solved, well-understood convention the way logical-property CSS is |
| Landing | More commits on the already-open `worktree-p2c-implementation` branch/PR | Explicit choice by the project owner; the branch has not merged yet |

### Rejected alternatives

- **Free-text language with no controlled RTL list** — simpler to implement, but makes
  `dir="rtl"` a per-run agent judgment call instead of a deterministic build-time
  lookup, which is untestable without invoking an agent in the test suite.
- **A one-off Hebrew-only hardcoded branch** — faster to ship once, but the moment a
  second language is requested, the whole mechanism (prompts, schema, build) has to be
  revisited instead of just adding a code to a list.
- **Separate RTL override CSS files per theme** — explicit and easy to read in
  isolation, but doubles the theme surface (6 files instead of 3) with no structural
  guarantee the two variants stay in sync as themes evolve.
- **Ask a clarifying question when the stated language is unresolvable** — consistent
  with how a human would handle genuine ambiguity, but breaks the skill's one
  invariant ("ask nothing, ever") for a single edge case; a hard fail (matching Phase
  0's existing bad-deck handling) keeps the rule absolute.

## Components changed

| File | Change |
|---|---|
| `SKILL.md` | Phase 0 gains language resolution: parse the user's stated language into `(name, ISO 639-1 code)`; hard-fail, in the same style as today's bad-deck exit codes, if unresolvable. Phase 1/2/3 dispatch prompts explicitly carry the resolved language to agents that only see their own topic/module slice. |
| `references/agents/summarizer.md` | Writes the `language` field into `outline.json`; module/topic titles are in the target language. |
| `references/agents/researcher.md`, `references/agents/course-writer.md` | Add: "write in `<language>`"; jargon terms stay in their original form inline, only definitions translate. |
| `references/agents/novice-simulator.md`, `references/agents/rubric-auditor.md` | Add: findings (`message`, `evidence`) stay in English regardless of course language. |
| `references/outline-schema.json` | New required top-level `language: {name: string, code: string}` object. |
| `scripts/p2c/outline.py` | Validate the new required field. |
| `scripts/p2c/build.py`, `scripts/p2c/theme.py` | New `RTL_LANGUAGES` constant (`he`, `ar`, `fa`, `ur`, `yi`, `dv`, `ps`, `sd`); deterministic `dir`/`lang` attribute emission from `outline.json`'s `language.code`; new template placeholders for both. |
| `assets/themes/*/theme.css`, `assets/print.css` | Converted from physical CSS properties to logical properties. Mermaid diagram containers explicitly forced `dir="ltr"` regardless of page direction. |
| `README.md` | Remove "No multi-language output" from "What this won't do"; document the now-required language parameter in Usage; note the RTL language list. |

## Data flow

1. User states a language in the request (required — e.g. "Turn week3.pdf into a
   Hebrew course"). Phase 0 resolves it to `(name, code)`. Unresolvable → hard stop,
   print the offending value, same shape as today's bad-deck exit codes.
2. Phase 1's summarizer writes `language` into `outline.json` alongside the outline it
   already produces.
3. Phase 2/3 dispatches (researcher, course-writer) receive the resolved language
   explicitly in their dispatch prompt, since they only ever see their own topic/module
   object, not the outline's top-level fields.
4. Phase 4's `build` reads `outline.json`'s `language.code`, looks it up against
   `RTL_LANGUAGES`, and emits `dir`/`lang` on the rendered `<html>` element via the
   existing template-placeholder mechanism.
5. Phase 5's reviewers read the (already-translated) `course.html` and write findings
   in English, per the Decisions table above.
6. The final report and `KNOWN-ISSUES.md` (if written) are in the target language,
   since both are student-facing.

## Error handling

- Stated language unresolvable → Phase 0 hard stop (mirrors today's exit-4/5 bad-deck
  handling), reporting the exact string the user gave.
- `language` missing from a summarizer's `outline.json` → falls through the existing
  schema-validation retry-once-then-stop path unchanged.

## Testing

- Deterministic (no agents): given a fixed `outline.json` with `language.code: "he"`
  and a fixed Hebrew module `.md` fixture, `build()` emits `dir="rtl" lang="he"`.
  Given `language.code: "en"` (or any non-RTL code), emits `dir="ltr" lang="en"`,
  unchanged from today's behavior.
- A grep-based CSS check: no bare physical directional properties
  (`margin-left`/`margin-right`/`text-align: left`) outside an explicitly
  `dir="ltr"`-scoped container (the Mermaid wrapper).
- A new Hebrew golden fixture (`course.md` → `course.html`), parallel to the existing
  English golden snapshot, locking in RTL rendering deterministically.
- `outline-schema.json` tests for the new required `language` field (valid and invalid
  cases).
- Confirm `p2c.invariants`' existing checks (quiz counts, TOC anchors, glossary-target
  links) remain language-agnostic as written; no changes expected, but verify rather
  than assume.
