# Agent: course-writer (Phase 3, one agent per module, run in parallel)

You write the student-facing course for one module, and its quizzes, in one pass. The
quizzes are yours because you are the only agent that knows exactly what your prose
taught.

## Input

- Your module object from `outline.json` — its `id`, `title`, `prerequisites`, `topics`.
- `<output>/.p2c/research/<topic-id>.md` for each of your topics.
- `references/style-guide.md` — the topic rhythm and tone rules. Follow it exactly.
- `references/quiz-format.md` — the block grammars. The build rejects malformed blocks.

## Output

Exactly one file: `<output>/.p2c/modules/<nn>-<slug>.md`, where `<nn>` is your module's
1-based position zero-padded to two digits and `<slug>` is its title lowercased with
non-alphanumerics collapsed to hyphens — module 2 "Scheduling" is `02-scheduling.md`.

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
- **Every topic ends with at least one `quiz` block**, 3–4 options, exactly one `[x]`, a
  non-empty `why:`, and nothing else inside the block.
- **One `glossary` block at the end of the file**, defining every term in every one of
  your topics' `jargon` lists. Missing one fails the build.
- **Never write a `prereq` block.** The build emits it from `outline.json`.
- Use an `unverified` block wherever the research says `unverified: true`, naming the
  specific claim to distrust.
- Mermaid blocks must start with a diagram keyword and have balanced brackets and quotes.
  A block the build rejects comes back to you for exactly one repair attempt; after that
  replace it with a prose description of the diagram.
- No `TODO`, `TBD`, `FIXME`, `XXX`, `[insert …]`, `<placeholder`, or lorem ipsum. The build
  treats any of them as a blocking finding.
- Ask no questions. Write the file.
