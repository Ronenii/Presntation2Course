<!-- topic: coherence -->
### Keeping caches consistent

Two processors, each with its own cache, can end up holding different values for the same
address. One of them is wrong, and neither knows it.

```analogy
Two people editing their own photocopy of the same page. Both edits look correct on the
copy in front of them, and the original now matches neither.
```

Hardware solves this with a coherence protocol. MESI assigns each cache line a state and
uses write-invalidate traffic on the bus to keep the states consistent, so a write in one
cache forces the others to drop their copy of that cache line.

<!-- no-visual: the outline calls for no diagram here; this fixture is deliberately narrow, isolating only the two reviewer-only defects it is designed to test. -->

```quiz
q: How many states does the MESI protocol define?
- [ ] Three
- [x] Four
- [ ] Five
why: The name itself is the mnemonic once you know it.
```

```glossary
Cache line: The fixed-size block of memory a cache transfers and tracks as one unit.
```
