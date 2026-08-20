<!-- topic: round-robin -->
### Round robin

Once several programs are runnable at the same time, someone has to decide who runs next
and for how long. Round robin makes the simplest possible choice.

```analogy
A tap being shared between people filling buckets. Nobody fills a whole bucket at once;
everyone gets a fixed number of seconds and then hands the tap on.
```

Each runnable process gets a fixed slice of CPU time — the quantum — and then goes to the
back of the queue. A short quantum makes the machine feel responsive but spends more time
switching between processes. A long quantum reduces that overhead and makes interactive
programs feel sluggish.

```animate
pattern: state-machine
states:
  - Ready
  - Running
  - Waiting
transitions:
  - Ready -> Running: scheduler picks it
  - Running -> Waiting: blocks on I/O
  - Waiting -> Ready: I/O completes
```

```animate
pattern: compare
left: First-come, first-served
right: Round robin
steps:
  - A long job blocks everything behind it | Each job gets a fixed slice
  - Short jobs wait for the whole queue | Short jobs finish early
```

```quiz
q: Halving the quantum on an interactive system usually has which effect?
- [x] Better response time, more time lost to context switching
- [ ] Better response time and higher total throughput
- [ ] No change, because each process still gets the same total share
why: The tempting answer is that responsiveness is free. It is not — the switching
     overhead is real work the CPU does instead of running your program.
```

```glossary
Quantum: The fixed slice of CPU time one process is allowed before the scheduler moves on.
```

<!-- topic: course-goals -->
### Course Goals

This course walks you through virtual memory from first principles: how addresses get
translated, why caching translations matters, and what happens when memory pressure
forces the system to choose what to evict. From there it moves to scheduling, where you
will see how the system decides who runs next once several programs are ready at once.

<!-- no-quiz: brief administrative topic, nothing to check -->

<!-- no-visual: an agenda summary has no mechanism to diagram; the two topics it previews already carry their own visuals. -->
