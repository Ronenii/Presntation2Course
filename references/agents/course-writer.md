# Agent: course-writer (Phase 3, one agent per module, run in parallel)

You write the student-facing course for one module, and its quizzes, in one pass. The
quizzes are yours because you are the only agent that knows exactly what your prose
taught.

## Input

- Your module object from `outline.json` — its `id`, `title`, `prerequisites`, `topics`.
- Each topic's `depth` (`"full"` or absent means the full rhythm below; `"brief"` means
  the exception in `references/style-guide.md`'s "Brief topics" section — plain prose
  only, no analogy, no visual, no quiz).
- `<output>/.p2c/research/<topic-id>.md` for each of your topics.
- `references/style-guide.md` — the topic rhythm and tone rules. Follow it exactly.
- `references/quiz-format.md` — the block grammars. The build rejects malformed blocks.

## Output

Exactly one file: write to the exact output path the orchestrator gives you in your
dispatch — do not derive or compute the filename yourself, even if it looks like it
should be `<output>/.p2c/modules/<nn>-<slug>.md` for a simple, Latin-script title.
Non-Latin-script titles (Hebrew, Arabic, ...) don't have an ASCII slug, so the
orchestrator always computes the real path itself and hands it to you directly — trust
that path, not any rule you might infer about how it was built.

Structure, exactly:

````markdown
<!-- topic: tlb -->
### What a TLB caches

Plain-language framing, two or three sentences.

```analogy
The analogy, and the sentence where it breaks down.
```

The technical explanation, naming each jargon term as you introduce it.

```mermaid
flowchart LR
  A[Virtual address] --> B[TLB]
```

A worked example with concrete numbers.

```quiz
q: A question answerable from the text above alone
- [ ] A plausible wrong answer
- [x] The right answer
- [ ] Another plausible wrong answer
why: Why the tempting wrong answer is wrong.
```

```unverified
The claim about X is not fully supported by the available sources.
```

<!-- topic: thrashing -->
### Thrashing

...

<!-- topic: course-goals -->
### Course Goals

This course walks you through virtual memory from first principles: how addresses get
translated, why caching translations matters, and what happens when memory pressure
forces the system to choose what to evict.

<!-- no-quiz: brief administrative topic, nothing to check -->
<!-- no-visual: brief administrative topic, nothing to check -->

```glossary
TLB: A small, fast cache holding recently used virtual-to-physical page mappings.
Working set: The pages a process is actively using in a given window of time.
```
````

## Mechanical requirements — the build fails without these

- **No `#` or `##` headings.** The build writes the course title and your module heading.
  Every topic is `###`.
- **Every topic opens with `<!-- topic: <id> -->`** using the id from `outline.json`,
  exactly. This is how the build proves no topic was dropped.
- **Every topic in your module appears, in outline order.** Do not merge, split, reorder,
  or invent topics.
- **Every `full`-depth topic ends with at least one `quiz` block**, 3–4 options, exactly
  one `[x]`, a non-empty `why:`, and nothing else inside the block. A `brief`-depth topic
  ends with `<!-- no-quiz: ... -->` instead — never both, never neither.
- **One `glossary` block at the end of the file**, defining every term in every one of
  your topics' `jargon` lists. Missing one fails the build.
- **Never write a `prereq` block.** The build emits it from `outline.json`.
- Write in the course's target language (`outline.json`'s `language`). Jargon terms
  themselves stay in their original form inline, exactly as they appear in the
  `jargon` list — only the surrounding prose and the glossary's *definitions*
  translate. The glossary block's `term:` side is the original-form term; only the
  text after the colon is written in the target language. Mermaid diagrams translate
  too: write each node's label in the target language, the same as prose — the
  diagram's container is always pinned left-to-right regardless of course language, but
  that is a rendering detail the build handles; it has no bearing on what language you
  write the labels in.
- Use an `unverified` block wherever the research says `unverified: true`, naming the
  specific claim to distrust.
- Mermaid blocks must start with a diagram keyword and have balanced brackets and quotes.
  A block the build rejects comes back to you for exactly one repair attempt; after that
  replace it with a prose description of the diagram. A prose description is not itself a
  visual, so when you replace a diagram this way also add
  `<!-- no-visual: diagram could not be rendered; described in prose instead -->` to that
  topic — otherwise it fails the build's visual-coverage check for an unrelated reason.
- No `TODO`, `TBD`, `FIXME`, `XXX`, `[insert …]`, `<placeholder`, or lorem ipsum. The build
  treats any of them as a blocking finding.
- Ask no questions. Write the file.

## Visual per topic

Every `full`-depth topic needs one of: a `mermaid` diagram, an inline `<svg>`, a `figure`
block, or an `animate` block. The build fails otherwise, unless you also write an
explicit `<!-- no-visual: <reason> -->` HTML comment for a topic that is genuinely
non-spatial — use that sparingly; it is an escape hatch, not a way to skip the visual
step because a diagram is inconvenient to write. A `brief`-depth topic also has no visual
step, but the build's visual check is not `depth`-aware — it only ever recognizes the
`no-visual` comment itself — so a `brief` topic must still write
`<!-- no-visual: <reason> -->` alongside its `<!-- no-quiz: ... -->`, even though it has
nothing to draw.

Pick the diagram type that matches the idea: `flowchart` for a process,
`sequenceDiagram` for an interaction between parties, `stateDiagram-v2` for a
lifecycle, `erDiagram`/`architecture-beta` for structure. Inline `<svg>` is
for a static structure a flow/sequence/state diagram cannot express (a memory
layout, a data structure). A second visual in one topic is rarely warranted —
only add one if the topic genuinely covers two separate spatial ideas.

If your dispatch tells you a topic already has a `reusable_image` (a real
slide image the summarizer flagged as worth reusing), do not author your own
visual for that topic at all — write a `figure` block instead, restating the
exact value you were given:

```figure
source: week1.pdf#12
caption: The lookup path, as drawn in the lecture.
```

Write only the caption yourself; the source value must be copied exactly
from your dispatch, never invented or re-derived.

When a topic is genuinely about a sequence or a before/after comparison, an
`animate` block is worth using instead of (or alongside) a mermaid diagram:

```animate
pattern: step-reveal
steps:
  - Request arrives at the TLB
  - TLB miss triggers a page-table walk
  - Page table entry is cached back into the TLB
```

```animate
pattern: state-toggle
before: Cache line marked Shared
after: Cache line marked Modified after a local write
```

`step-reveal` needs at least 2 steps; `state-toggle` needs both `before:` and
`after:`. See `references/quiz-format.md` for the full grammar.

Use `array-ops` when a topic is about an array/list transformation you can express
as a short sequence of compare/swap/highlight steps (e.g. one pass of a sort, a
partition step). Use `path-trace` when a topic is about a value moving along a
continuous path — a point sliding along a plotted curve, a traversal along a tree
or graph edge — and you can supply the path as literal (x, y) coordinate pairs
(never write a function expression; give the actual point list).
