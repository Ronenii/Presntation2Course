# Style guide

You are writing for a student revising alone, weeks after the lecture, with only this
page. They are intelligent and have no shame about not knowing your vocabulary.

## The topic rhythm — fixed, in this order

1. **Plain-language framing.** What problem does this exist to solve? Two or three
   sentences, no terminology the student has not met. Never open with a definition.
2. **Analogy.** An `analogy` block. It comes **before** the technical content, never
   after. This ordering is the entire point of the project.
3. **Technical content.** Now name the thing and be precise. Introduce each jargon term
   the moment you first use it.
4. **Visual.** One of: a `mermaid` diagram, an inline `<svg>` when the idea is not a flow,
   sequence, state, or architecture, a `figure` block when the topic already has a
   `reusable_image`, or an `animate` block when the topic is a sequence or a before/after
   comparison. The build fails a topic with none of these. Skip it only when the topic is
   genuinely non-spatial, and only with an explicit `<!-- no-visual: <reason> -->` HTML
   comment — there is no silent skip.
5. **Worked example.** Concrete numbers, a concrete trace, or a concrete scenario.
6. **Quiz.** One or more `quiz` blocks. Every topic ends with at least one, except a
   `brief` topic — see "Brief topics" below.

## Brief topics — the exception to the rhythm

A topic marked `"depth": "brief"` in the outline skips the rhythm above entirely. Write
1–2 short plain-language paragraphs and stop: no `analogy` block, no visual, no worked
example, no `quiz`. Close the topic with **both** `<!-- no-quiz: brief administrative
topic -->` and `<!-- no-visual: brief administrative topic -->` (or a more specific
reason) instead of a quiz block or a diagram — those comments are what tell the build
this topic was deliberately left unchecked and undiagrammed, not that a quiz or a visual
was forgotten. The build has no awareness of `depth` itself; it only ever recognizes
these two justification comments, so both are required even though the topic is `brief`.

This is not a shortcut for content that is merely short — a two-sentence topic with a
real mechanism to check still gets the full rhythm, just briefly. `brief` is only for
topics the outline flagged as having nothing to teach or check in the first place (course
goals, an agenda, a roadmap slide).

## Tone

- Second person. "You" the student, not "the reader" and not "we".
- Short sentences. If a sentence needs a comma-spliced subordinate clause to survive,
  split it.
- Prefer the concrete noun to the abstract one: "the page table", not "the mapping
  mechanism".
- No filler openers: "In this section we will explore", "It is important to note that",
  "As we all know". Delete them and start with the content.
- No exhortation. Do not tell the student that something is exciting, elegant, or simple.
  If it is simple they will notice.

## Analogies

- One analogy per topic. Two competing analogies teach neither.
- The analogy must map onto the mechanism, not merely onto the mood. State what maps to
  what.
- **State where it breaks.** One sentence: "the analogy stops working when …". An analogy
  that breaks down silently teaches something false, and that is a blocking review
  finding.
- Draw from ordinary life — kitchens, post, queues, keys, notebooks. Never from another
  technical field the student may not know.

## Jargon

- Every term in the topic's `jargon` list must appear in the module's `glossary` block.
- Define on first use in the prose too. The glossary is a safety net, not the explanation.
- Do not use a term in a definition of another term unless that term is also defined.

## Quizzes

- Test understanding, not recall of a sentence you just wrote.
- Every distractor must be plausible — something a student who half-followed would pick.
  Never pad with an obviously silly option.
- `why:` must address the **tempting wrong answer**, not restate the right one. That is
  where the teaching happens.
- The question must be answerable from this course alone. A question needing outside
  knowledge is a blocking review finding.

## Honesty

- If the research file says `unverified: true`, say so in an `unverified` block and hedge
  the specific claim. **Never invent a confident explanation.** A student who cannot tell
  the difference is worse off with invention than with an admitted gap.
- Never state a number, date, or name that neither the deck nor a cited source supports.
- Do not smooth over a contradiction in the deck. Name it.

## Length

Aim for 250–600 words of prose per topic, excluding blocks. A topic that needs more is
probably two topics; report that rather than writing 1500 words.
