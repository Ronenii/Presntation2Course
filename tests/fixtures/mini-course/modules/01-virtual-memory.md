<!-- topic: tlb -->
### What a TLB caches

Every memory access your program makes uses an address that does not exist in hardware.
Something has to turn it into a real one, on every single access, without slowing the
machine to a crawl.

```analogy
Imagine looking up a colleague's extension in a 400-page directory every time you call
them. You would write the four numbers you actually dial on a sticky note. The sticky
note is not a copy of the directory — it is a copy of the lookups you keep repeating.
```

The TLB is that sticky note. It stores recently used virtual-to-physical page mappings so
the processor can skip walking the page table. On a hit, translation costs almost nothing.
On a miss, the hardware walks the full structure and installs the result.

```figure
source: terse.pdf#1
caption: The original slide this diagram is redrawn from.
```

```animate
pattern: transform
from: A virtual address
to: A physical address
steps:
  - Split into page number and offset
  - Look the page number up in the TLB
```

```quiz
q: What does a TLB actually cache?
- [ ] The contents of recently used pages
- [x] Virtual-to-physical page mappings
- [ ] The page table itself
why: It caches translations, not data. Confusing it with a data cache is the most common
     mistake here — the TLB sits in front of the page table, not in front of memory.
```

<!-- topic: thrashing -->
### Thrashing

Paging is normal. Thrashing is what happens when paging stops being a background cost and
becomes the entire workload.

```analogy
A desk with room for three open books. With four books in play you spend your time
swapping books in and out of the drawer instead of reading any of them.
```

The set of pages a process actively needs is its working set. When the combined working
sets exceed physical memory, every process evicts pages another process is about to want,
and useful work collapses while the disk stays busy.

<!-- no-visual: purely a resource-accounting argument (sum of working sets vs. available frames); the outline calls for no diagram here. -->

```quiz
q: A machine shows heavy disk activity and near-zero throughput. Why does that point to
   thrashing rather than a slow disk?
- [x] The working sets no longer fit in memory, so processes keep evicting each other
- [ ] The disk queue is saturated by one large sequential read
- [ ] The page table has grown too large to search
why: A slow disk would still let useful work proceed between reads. The tell is that the
     paging is caused by the processes' own mutual eviction, so adding memory helps and a
     faster disk barely does.
```

```glossary
TLB: A small, fast cache holding recently used virtual-to-physical page mappings.
Page table: The full in-memory map from virtual pages to physical frames.
Working set: The pages a process is actively using in a given window of time.
```
