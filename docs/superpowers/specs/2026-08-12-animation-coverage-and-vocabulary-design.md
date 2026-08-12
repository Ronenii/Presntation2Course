# Animation coverage floor and domain-general pattern vocabulary

## Context

Live review of a generated course (`unit2_lecture_tutorial-course`, monocular depth
estimation, 55 topics) found **zero** `animate` blocks. The visual mix was:

| Visual | Count |
|---|---|
| `mermaid` | 42 (39 `flowchart`, 3 `graph`) |
| `animate` | **0** |
| inline `<svg>` | 1 |
| `figure` | 2 |
| `no-visual` justification | 10 |

Of those 42 mermaid blocks, **17 are linear chains with no fan-out** — a straight line
of boxes, where no node is the source of more than one edge. `references/agents/course-writer.md`
already tells the writer that exactly this shape is a `state-machine` candidate and not
a flowchart ("If you'd draw it in mermaid it would be a straight line of boxes with no
fan-out — that shape is a `state-machine` candidate, not a flowchart"). The writer had
the rule and did not follow it.

The user's assessment, verbatim: courses "time after time come out bland," animations are
"absolutely a requirement," and the animation share should have a floor of **25%,
ideally more.**

### Two independent causes

**1. Nothing enforces animation use.** `scripts/p2c/validate.py:180-186` enforces only
that *a visual exists* per `full`-depth topic — `mermaid`, `figure`, inline `<svg>`, and
`animate` all satisfy it equally. Mermaid is the lower-effort option (freeform text vs. a
strict grammar the build can reject) and is never penalized, while a malformed `animate`
block costs the writer a repair attempt before being discarded. The incentive gradient
points entirely at mermaid. Prose guidance loses to an unenforced constraint; the
visual-coverage check itself only started working once it became a build failure.

**2. The pattern vocabulary is too narrow to be interesting.** The four patterns are
`state-machine`, `state-toggle`, `array-ops`, `path-trace`. Two of them (`array-ops`,
`path-trace`) are CS-theory-specific and unusable for a vision/ML course — or for most
non-algorithms subjects. That leaves `state-machine`, which renders as a row of rects
with a fill swap.

**Order matters.** Fixing (1) alone converts ~14 linear flowcharts into grey-box
`state-machine`s: the floor is met, the course still looks bland. That is compliance
without improvement, and it would actively train the writer to produce
boring-but-passing output. The vocabulary must be widened *first*, then the floor
enforced.

### Research: three external repositories

The user asked whether three repos could enhance or be bundled with P2C.

**`careerhackeralex/visualize`** (MIT, 196★) — a Claude Code plugin generating
standalone HTML visualizations (dashboards, decks, infographics) from a prompt.
**Not bundled: wrong shape.** It is a whole-page generator; P2C needs per-topic blocks
inside an existing pipeline with its own theme tokens, validation, and RTL handling.
Nothing to adopt beyond its quality-bar framing.

**`supermemoryai/skills/svg-animations`** (**no license file**) — a technique reference
covering `stroke-dasharray`/`stroke-dashoffset` path drawing, SMIL (`<animate>`,
`<animateTransform>`, `<animateMotion>`), shape morphing, pulsing, and gradient shifts.
**Not bundled: unlicensed, and no text is copied from it.** Its freeform authoring model
is also wrong for us — unvalidatable freeform SVG from an LLM is the exact problem the
bounded `animate` grammar exists to prevent. We independently apply the standard,
widely-documented web techniques it describes (dash-offset stroke drawing, staggered
reveals) inside our own renderers.

**`cathrynlavery/diagram-design`** (MIT, 7,453★, actively pushed) — 27 editorial diagram
types as self-contained HTML + inline SVG, explicitly anti-mermaid ("Reproducing
Mermaid's renderer layout" is a listed anti-pattern). **Not vendored**, for two concrete
reasons: it has **zero animation support** (verified by grep over the full tree), and it
hardcodes its own fonts (Instrument Serif / Geist / Geist Mono) and palette, which would
fight P2C's per-domain `--color-*` theme tokens and its RTL/Hebrew support. We adopt its
**geometry and restraint rules** as design constraints on our own renderers:

- Rounded right-angle (orthogonal) connectors, quarter-arc bends at `r=8`; no diagonals.
- Arrow/stage labels always over an opaque mask rect, with a visible 6–10px gap so the
  connector remains traceable.
- Accent reserved for 1–2 focal elements ("using it on 5 nodes erases the signal").
- Layout constants (box widths, heights, gaps, margins) divisible by 4. This applies to
  the new patterns' own constants only — the existing patterns keep their current
  geometry (`_STATE_BOX_WIDTH = 130`, `_BAR_GAP = 18`, `_PATH_PADDING = 10` are not
  4-divisible and are not being re-laid-out here). Derived values — text baselines,
  centers, midpoints — are exempt; centering inside a 4-divisible box legitimately
  produces odd numbers.
- No shadows; border radius ≤10px.
- Target density 4/10 — above ~9 nodes it is two diagrams.

## Scope decision

The user chose approach **(B)** from three offered: keep `mermaid` for genuinely
branching structures, add richer `animate` patterns, and route *linear* sequences to new
animated SVG renderers. Rejected: (A) restyle mermaid only — mermaid's auto-layout cannot
produce orthogonal elbows or fanned attach points; (C) replace mermaid wholesale — every
diagram becomes our maintenance burden.

Two further user decisions:

- **Domain-general patterns**, not vision/ML-specific ones — P2C generates courses across
  varied subjects, and per-domain patterns would go unused elsewhere.
- **No stroke-reveal treatment for existing mermaid diagrams.** The animation share is
  therefore counted from real `animate` blocks only, which keeps the 25% floor meaningful
  rather than cosmetic.

## Architecture

### Three new domain-general patterns

Additive. All four existing patterns keep their current grammar and rendering;
`state-toggle` remains correct for genuine two-state contrasts.

`parse_animate` (`scripts/p2c/mdrender.py:127`) is already a key/list-section parser with
a `lists` dict and a `_LIST_HEADERS` map; new patterns slot in by extending those maps and
adding a validation branch, without disturbing the existing four.

#### `pipeline`

The highest-value shape — it covers most of unit 2's 17 misclassified linear chains.
Input flowing through named stages, each transforming it.

````
```animate
pattern: pipeline
stages:
  - Raw image: single RGB frame, no depth information
  - Encoder: compresses the frame into a feature map
  - Decoder: expands features back to per-pixel values
  - Depth map: one distance estimate per pixel
```
````

`stages:` needs 2–6 entries, each `name: what changes`. Both halves are required — a
stage without a transformation description is what makes a diagram a static flowchart
rather than a sequence worth watching.

#### `layer-stack`

Abstraction tiers building up, or a signal passing down through them.

````
```animate
pattern: layer-stack
direction: up
layers:
  - Pixels: raw sensor values
  - Edges: local intensity changes
  - Textures: repeated edge patterns
  - Objects: assembled shapes
```
````

`layers:` needs 2–6 entries, listed **bottom-up**. `direction:` is optional and defaults
to `up`; `down` animates from the top layer downward for top-down decompositions.

#### `transform`

One entity becoming another through labeled intermediate steps — the before/after that
`state-toggle` cannot express because it has middles.

````
```animate
pattern: transform
from: Disparity map
to: Metric depth map
steps:
  - Invert each disparity value
  - Scale by the focal-length/baseline constant
```
````

`from:` and `to:` are both required; `steps:` needs 1–4 entries.

### Why these will not render bland

The current `state-machine` renders as a row of rects with a fill swap; that is the
blandness. The new renderers apply, in addition to the diagram-design geometry rules
above:

- **Stroke drawing** — connectors between stages animate `stroke-dashoffset` from the
  path length to 0, so the diagram draws itself rather than blinking on. Path lengths are
  computed in Python at render time (the paths are ours, so lengths are known), not via
  `getTotalLength()` at runtime.
- **Staggered entry** — anime.js stagger across stage groups so content builds in
  sequence.
- **Accent discipline** — exactly one stage carries `--color-accent` at a time; all others
  sit at muted/idle tokens. One focal element at a time is what makes a sequence readable,
  and it is the direct application of diagram-design's focal rule.

### Two anime.js gotchas that apply

Both are documented in `.claude/skills/animejs/references/api-reference.md` and were
established by the earlier anime.js migration
(`docs/superpowers/specs/2026-08-02-animejs-animation-migration-design.md`). The new
renderers must honor them:

1. **SVG `transform` attribute vs. CSS `transform` property.** anime.js sets a CSS
   `transform`, which fully replaces (does not compose with) an SVG `transform`
   *attribute*. Any element needing both a fixed base position and an animated offset
   carries its base position in plain attributes (`x`/`y`/`cx`/`cy`), never in
   `transform="translate(...)"`.
2. **Absolute keyframe values compound across `loop: true`.** A step animating *to* a
   literal value starts from wherever the previous lap left it. Every looping timeline
   ends with an explicit `tl.set(...)` snapping animated properties back to baseline.

### Accessibility, print, and RTL

Each new pattern follows the existing per-pattern precedent in `assets/base/layout.css`:

- **`prefers-reduced-motion` and print** render fully static with *every* stage/layer/step
  visible at once — not a single frozen frame. This mirrors the existing rules scoped to
  `.anim--array-ops` and the `state-machine` toggle-pair pattern.
- **RTL**: each new SVG root carries `dir="ltr"`, exactly as
  `mdrender.py:637`/`:841`/`:952` already do, so a Hebrew course's animations keep their
  left-to-right geometry while labels stay in the course language.

### Enforcing the 25% floor

A new check in `scripts/p2c/validate.py`.

**Denominator: topics that owe a visual** — i.e. every topic without a `no-visual`
justification. `brief` topics carry that comment by rule and so drop out; including them
would make the floor unreachable on an admin-heavy deck. In unit 2 this denominator is
~45 topics, putting the floor at ~12 animations.

**Required count is `ceil(0.25 * visual_owing_topics)`,** so the floor rounds up rather
than letting a fractional requirement be satisfied by truncation. A module with fewer
than 4 such topics therefore still requires 1 animation. The check is skipped entirely
when the denominator is 0.

**Determining `full` vs. `brief`.** The build is not `depth`-aware today — `mdrender.py`
only recognizes the `<!-- no-visual: ... -->` and `<!-- no-quiz: ... -->` justification
comments, never the outline's `depth` field. The check therefore derives its denominator
from rendered structure rather than from the outline: a topic counts toward the
denominator when it is **not** justified by a `no-visual` comment. This makes `brief`
topics (which are required to carry `no-visual`) drop out automatically, and it means the
denominator is exactly the set of topics the existing `topic_without_visual` check already
polices — one definition of "a topic that owes a visual," not two.

**Blocking, not advisory** — routed to `writer` in the same manner as the existing
`topic_without_visual` code. Prose guidance already failed once here; a warning would fail
the same way.

**The finding names the specific topics to convert.** A bare "you need 25%" invites
padding. The check runs a linear-chain detector over each topic's mermaid blocks — the
same rule used to find the 20 in unit 2: *a mermaid block where no node is the source of
more than one edge.* Topics whose only visual is such a chain are listed in the finding as
the concrete conversion candidates, so the writer is told which diagrams are misclassified
rather than merely that the count is short.

This makes the floor achievable by genuine reclassification. Unit 2 had 17 such chains
against a floor of ~12 — the material to satisfy it honestly was already there.

## Components

| File | Change |
|---|---|
| `scripts/p2c/mdrender.py` | `parse_animate` accepts `pipeline`, `layer-stack`, `transform` (extend `lists`, `_LIST_HEADERS`, the pattern whitelist at `:172`, and per-pattern validation); three new `_*_html` renderers; dispatch in `_animate_html` (`:342`) |
| `scripts/p2c/validate.py` | 25%-floor check with linear-chain mermaid detector; new finding code routed to `writer` |
| `assets/base/layout.css` | Idle/active/accent tokens per new pattern; `prefers-reduced-motion` + print static fallbacks |
| `assets/base/course.js` | Timeline construction for the three patterns, extending `wireAnimations` (`:406`) |
| `references/quiz-format.md` | Grammar reference for the three patterns |
| `references/agents/course-writer.md` | Selection guidance and the 25% requirement |

## Testing

- **Parser**: valid/invalid cases per new pattern — bounds (2–6 stages/layers, 1–4 steps),
  missing required keys (`from:`/`to:`, a stage's `: what changes` half), cross-pattern key
  rejection (e.g. `points:` inside a `pipeline`), mirroring the existing
  `state-machine`/`state-toggle` parser tests.
- **Renderer**: golden-file coverage for each new pattern; assert `dir="ltr"` on each SVG
  root; assert the new patterns' layout constants are divisible by 4.
- **Validator**: a course under the floor produces the finding and names the linear-chain
  topics; a course at or above it does not; the denominator excludes `no-visual`-justified
  topics (a `brief`-heavy course does not fail spuriously); the requirement rounds up
  (3 owing topics still require 1 animation) and the check is skipped at a denominator of
  0; a course whose mermaid blocks all branch produces the floor finding without falsely
  naming them as conversion candidates.
- **Static fallback**: reduced-motion/print CSS reveals all stages, verified the same way
  the existing patterns' fallbacks are.

## Out of scope

- Stroke-reveal for existing mermaid diagrams (explicitly declined).
- Replacing mermaid for branching structures.
- Vendoring any of the three researched repositories.
- Vision/ML-specific patterns.
