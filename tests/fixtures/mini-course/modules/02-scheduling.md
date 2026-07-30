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
pattern: step-reveal
steps:
  - A process becomes ready to run
  - The scheduler picks it from the ready queue
  - It runs until it blocks, yields, or is preempted
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
