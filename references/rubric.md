# Review rubric

Two reviewers run in parallel over the built course. Findings split into **blocking**,
which cost another pass, and **noted**, which are recorded and never looped. Without that
split the loop cannot terminate, because there is always something a reviewer could
improve.

## Blocking findings

| Code | Meaning |
|---|---|
| `jargon_undefined` | A term is used before it is defined, or never defined at all. |
| `topic_without_quiz` | A topic ends without a comprehension check. |
| `quiz_needs_outside_knowledge` | A question cannot be answered from the course alone. |
| `unsupported_claim` | A claim traceable to neither the deck nor a cited source. |
| `missing_background` | The course asserts something it never explains — a gap the research missed. |
| `topic_missing` | A topic in `outline.json` does not appear in the course. |
| `analogy_misleading` | An analogy breaks down in a way that teaches something false. |
| `render_failure` | The page is structurally broken: a diagram did not render, a quiz has no options. |

## Noted findings

| Code | Meaning |
|---|---|
| `verbosity` | Longer than it needs to be. |
| `style` | Tone, rhythm, or wording that could be better. |
| `missing_visual` | A diagram would help but its absence does not block understanding. |
| `other` | Anything else worth recording. |

An analogy you merely dislike is `style`. An analogy that would leave a student with a
false model is `analogy_misleading` and blocks.

## Output contract

Write exactly one file, `<output>/.p2c/review/pass-<n>.json`:

```json
{
  "reviewer": "novice-simulator",
  "pass": 1,
  "findings": [
    {
      "code": "jargon_undefined",
      "message": "'MESI' is used in Keeping caches consistent and never defined",
      "module": "m-cache",
      "topic": "coherence",
      "evidence": "MESI assigns each cache line a state"
    }
  ]
}
```

- `code` must be from the tables above. Do not invent codes.
- `message` says what is wrong, specifically enough to fix without guessing.
- `evidence` quotes the course. A finding with no evidence is not actionable.
- `module` and `topic` decide which single unit re-runs. Omitting them widens the re-run,
  so fill them in whenever you can tell.
- Do not supply `route` or `blocking`; both are assigned from the code.
- An empty `findings` list is a valid and welcome result.

## Routing

| Finding | Re-runs |
|---|---|
| `missing_background`, `unsupported_claim` | that one topic's researcher |
| `jargon_undefined`, `quiz_needs_outside_knowledge`, `analogy_misleading`, `topic_without_quiz` | that one module's writer |
| `topic_missing` | the summarizer's gap list, then that topic forward |
| `render_failure` | the build script, no agent |

## Convergence

Hard cap of three passes. Early exit as soon as a pass produces no new blocking findings.
A finding that reappears after being marked fixed is recorded, not re-fixed. Whatever
blocking findings survive pass three are written to `KNOWN-ISSUES.md` and shipped with the
course, because the student needs to know which parts to distrust.
