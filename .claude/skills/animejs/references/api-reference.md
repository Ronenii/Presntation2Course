# Anime.js v4 Complete API Reference

## animate(targets, parameters)

Animates the properties of targeted elements.

### Targets

| Type | Example |
|------|---------|
| CSS Selector | `'.class'`, `'#id'`, `'div'` |
| DOM Element | `document.querySelector('.el')` |
| NodeList | `document.querySelectorAll('.el')` |
| JavaScript Object | `{ prop: 0 }` |
| Array | `[el1, el2, { prop: 0 }]` |

### Animatable Properties

#### CSS Properties
```javascript
animate('.el', {
  opacity: 0.5,
  backgroundColor: '#FFF',
  borderRadius: '50%',
  width: '200px',
  height: '200px'
});
```

#### CSS Transforms (Individual)
```javascript
animate('.el', {
  translateX: 250,        // px by default
  translateY: '50%',
  translateZ: 100,
  rotate: '1turn',        // or deg, rad
  rotateX: 45,
  rotateY: 45,
  rotateZ: 45,
  scale: 2,
  scaleX: 1.5,
  scaleY: 1.5,
  scaleZ: 1.5,
  skewX: 30,
  skewY: 30,
  perspective: 1000
});
```

#### CSS Variables
```javascript
animate('.el', {
  '--custom-property': 100
});
```

#### JavaScript Object Properties
```javascript
const obj = { value: 0, x: 0 };
animate(obj, {
  value: 100,
  x: 500
});
```

#### HTML Attributes
```javascript
animate('input[type="range"]', {
  value: 100
});
```

#### SVG Attributes
```javascript
animate('circle', {
  cx: 100,
  cy: 100,
  r: 50
});
```

### Tween Value Types

#### Numerical (unitless)
```javascript
{ translateX: 250 }  // Becomes '250px'
{ opacity: 0.5 }     // No unit
{ rotate: 90 }       // Becomes '90deg'
```

#### Unit Conversion
```javascript
{ width: '50%' }
{ translateX: '10rem' }
{ rotate: '1turn' }
```

#### Relative Values
```javascript
{ translateX: '+=100' }  // Add 100
{ translateX: '-=100' }  // Subtract 100
{ scale: '*=2' }         // Multiply by 2
```

#### From/To
```javascript
{ translateX: [0, 250] }           // From 0 to 250
{ opacity: { from: 0, to: 1 } }    // Explicit from/to
```

#### Color Values
```javascript
{ color: '#FF0000' }
{ backgroundColor: 'rgb(255, 0, 0)' }
{ borderColor: 'hsl(0, 100%, 50%)' }
```

#### Function-Based Values
```javascript
animate('.el', {
  translateX: (el, i, total) => i * 50,
  rotate: (el, i, total) => {
    return anime.random(-180, 180);
  }
});
```

### Tween Parameters (Per-Property)

```javascript
animate('.el', {
  translateX: {
    to: 250,
    from: 0,
    delay: 100,
    duration: 500,
    ease: 'outExpo',
    composition: 'blend',  // 'none', 'replace', 'blend'
    modifier: v => Math.round(v)
  },
  rotate: {
    to: '1turn',
    duration: 1000
  }
});
```

### Keyframes

#### Array Keyframes
```javascript
animate('.el', {
  translateX: [0, 100, 50, 200],  // Equal duration each
  scale: [1, 1.5, 1]
});
```

#### Object Keyframes (Duration-Based)
```javascript
animate('.el', {
  translateX: [
    { to: 100, duration: 500 },
    { to: 50, duration: 300 },
    { to: 200, duration: 400 }
  ]
});
```

#### Percentage-Based Keyframes
```javascript
animate('.el', {
  keyframes: [
    { translateX: 0, at: '0%' },
    { translateX: 100, at: '25%' },
    { translateX: 50, at: '75%' },
    { translateX: 200, at: '100%' }
  ],
  duration: 2000
});
```

### Playback Settings

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `delay` | Number/Function | 0 | Delay before animation starts (ms) |
| `duration` | Number/Function | 1000 | Animation duration (ms) |
| `loop` | Number/Boolean | false | Number of loops, or true for infinite |
| `loopDelay` | Number | 0 | Delay between loops (ms) |
| `alternate` | Boolean | false | Alternate direction on loop |
| `reversed` | Boolean | false | Play in reverse |
| `autoplay` | Boolean/ScrollObserver | true | Auto-start animation |
| `frameRate` | Number | undefined | Limit frame rate |
| `playbackRate` | Number | 1 | Playback speed multiplier |
| `playbackEase` | String/Function | undefined | Easing for entire playback |
| `persist` | Boolean | true | (WAAPI) Keep styles after animation |

### Callbacks

```javascript
animate('.el', {
  translateX: 250,
  onBegin: (anim) => console.log('Started'),
  onComplete: (anim) => console.log('Completed'),
  onUpdate: (anim) => console.log(anim.progress),
  onLoop: (anim) => console.log('Looped'),
  onPause: (anim) => console.log('Paused'),
  onBeforeUpdate: (anim) => {},  // Before each frame
  onRender: (anim) => {}         // After render
}).then(anim => {
  console.log('Promise resolved');
});
```

### Animation Methods

```javascript
const anim = animate('.el', { translateX: 250 });

anim.play();          // Start/resume
anim.pause();         // Pause
anim.restart();       // Restart from beginning
anim.reverse();       // Reverse direction
anim.alternate();     // Toggle direction
anim.resume();        // Resume from paused
anim.complete();      // Jump to end
anim.reset();         // Reset to initial state
anim.cancel();        // Cancel and clear
anim.revert();        // Revert all changes
anim.seek(500);       // Seek to 500ms
anim.seek('50%');     // Seek to 50%
anim.stretch(2000);   // Stretch to new duration
anim.refresh();       // Refresh targets/values
```

### Animation Properties

```javascript
anim.currentTime      // Current time in ms
anim.progress         // Progress 0-1
anim.paused           // Is paused
anim.began            // Has begun
anim.completed        // Is completed
anim.reversed         // Is reversed
anim.duration         // Total duration
anim.targets          // Target elements
```

---

## createTimeline(parameters)

Creates a timeline to synchronize multiple animations.

### Basic Usage

```javascript
import { createTimeline } from 'animejs';

const tl = createTimeline({
  defaults: { duration: 500, ease: 'outExpo' },
  loop: true,
  alternate: true
});

tl.add('.box1', { translateX: 100 })
  .add('.box2', { translateX: 100 })
  .add('.box3', { translateX: 100 });
```

### Time Position

| Position | Description | Example |
|----------|-------------|---------|
| Absolute | Milliseconds from start | `500` |
| `'<'` | Start of previous | `'<'` |
| `'>'` | End of previous | `'>'` |
| `'<+=100'` | 100ms after previous start | `'<+=100'` |
| `'<-=100'` | 100ms before previous start | `'<-=100'` |
| `'>=+100'` | 100ms after previous end | `'>=+100'` |
| Label | Jump to label | `'myLabel'` |

```javascript
tl.label('intro')
  .add('.a', { x: 100 })
  .add('.b', { x: 100 }, '<')        // Same time as .a
  .add('.c', { x: 100 }, '<+=200')   // 200ms after .a starts
  .add('.d', { x: 100 }, 'intro')    // At label position
  .add('.e', { x: 100 }, 1000);      // At 1000ms absolute
```

### Timeline Methods

```javascript
tl.add(target, params, position);   // Add animation
tl.add(timerParams, position);      // Add timer
tl.set(target, params, position);   // Instant set
tl.call(fn, position);              // Call function
tl.sync(otherTimeline, position);   // Sync timeline
tl.label('name', position);         // Add label
tl.remove(animation);               // Remove animation
tl.init();                          // Initialize

// Playback controls (same as animation)
tl.play() / pause() / restart() / reverse() / etc.
```

---

## createTimer(parameters)

Alternative to setTimeout/setInterval that stays in sync with animations.

```javascript
import { createTimer } from 'animejs';

const timer = createTimer({
  duration: 1000,
  loop: 5,
  onUpdate: (self) => console.log(self.currentTime),
  onComplete: () => console.log('Done')
});
```

---

## stagger(value, parameters)

Creates staggered values for multiple targets.

### Time Staggering

```javascript
animate('.el', {
  translateX: 250,
  delay: stagger(100)              // 0, 100, 200, 300...
});

animate('.el', {
  translateX: 250,
  delay: stagger(100, { start: 500 })  // 500, 600, 700...
});
```

### Values Staggering

```javascript
animate('.el', {
  scale: stagger([0.5, 1.5]),     // Range from 0.5 to 1.5
  rotate: stagger([-45, 45])
});
```

### Stagger Parameters

| Parameter | Description |
|-----------|-------------|
| `start` | Starting value |
| `from` | Origin: 'first', 'last', 'center', index, [x, y] |
| `reversed` | Reverse order |
| `ease` | Easing function |
| `grid` | Grid dimensions [cols, rows] |
| `axis` | Grid axis: 'x', 'y' |
| `modifier` | Transform function |

```javascript
// Grid stagger from center
animate('.grid-item', {
  scale: [0, 1],
  delay: stagger(50, {
    grid: [10, 10],
    from: 'center',
    ease: 'outQuad'
  })
});
```

---

## onScroll(parameters)

Creates scroll-triggered animations.

```javascript
import { animate, onScroll } from 'animejs';

// Play on scroll enter
animate('.el', {
  translateX: 250,
  autoplay: onScroll({
    target: '.el',
    enter: 'bottom right'
  })
});

// Sync with scroll position
animate('.el', {
  translateX: [0, 500],
  autoplay: onScroll({
    target: '.scroll-container',
    sync: true
  })
});
```

### ScrollObserver Settings

| Parameter | Description |
|-----------|-------------|
| `container` | Scroll container (default: window) |
| `target` | Element to observe |
| `axis` | 'y' or 'x' |
| `debug` | Show debug markers |
| `repeat` | Repeat on re-enter |
| `enter` | Enter threshold |
| `leave` | Leave threshold |
| `sync` | Synchronize with scroll position |

### ScrollObserver Callbacks

```javascript
onScroll({
  target: '.el',
  onEnter: (self) => {},
  onEnterForward: (self) => {},
  onEnterBackward: (self) => {},
  onLeave: (self) => {},
  onLeaveForward: (self) => {},
  onLeaveBackward: (self) => {},
  onUpdate: (self) => {},
  onSyncComplete: (self) => {}
});
```

---

## createDraggable(target, parameters)

Creates draggable elements.

```javascript
import { createDraggable, createSpring } from 'animejs';

const draggable = createDraggable('.element', {
  container: '.container',
  x: { snap: 50 },
  y: { snap: 50 },
  releaseEase: createSpring({ stiffness: 200, damping: 20 }),
  onGrab: (self) => {},
  onDrag: (self) => {},
  onRelease: (self) => {},
  onSnap: (self) => {},
  onSettle: (self) => {}
});

// Methods
draggable.setX(100);
draggable.setY(100);
draggable.disable();
draggable.enable();
draggable.reset();
draggable.revert();
```

---

## SVG Utilities

### morphTo(shape)

```javascript
import { animate, morphTo } from 'animejs';

animate('path#shape1', {
  d: morphTo('path#shape2')
});
```

### createDrawable(path)

```javascript
import { animate, createDrawable } from 'animejs';

const drawable = createDrawable('path.line');
animate(drawable, {
  draw: ['0 0', '0 1'],  // [start, end] normalized
  duration: 2000
});
```

### createMotionPath(path)

```javascript
import { animate, createMotionPath } from 'animejs';

animate('.element', {
  ...createMotionPath('path.curve'),
  duration: 3000
});
```

---

## splitText(target, parameters)

Splits text into animatable elements.

```javascript
import { splitText, animate, stagger } from 'animejs';

const { lines, words, chars } = splitText('h1', {
  lines: true,
  words: true,
  chars: true
});

animate(chars, {
  translateY: [20, 0],
  opacity: [0, 1],
  delay: stagger(30)
});
```

---

## Easings

### Built-in Easings

| In | Out | InOut |
|----|-----|-------|
| `inQuad` | `outQuad` | `inOutQuad` |
| `inCubic` | `outCubic` | `inOutCubic` |
| `inQuart` | `outQuart` | `inOutQuart` |
| `inQuint` | `outQuint` | `inOutQuint` |
| `inSine` | `outSine` | `inOutSine` |
| `inExpo` | `outExpo` | `inOutExpo` |
| `inCirc` | `outCirc` | `inOutCirc` |
| `inBack` | `outBack` | `inOutBack` |
| `inElastic` | `outElastic` | `inOutElastic` |
| `inBounce` | `outBounce` | `inOutBounce` |

### Custom Easings

```javascript
// Cubic Bezier
{ ease: 'cubicBezier(0.5, 0, 0.5, 1)' }

// Steps
{ ease: 'steps(5)' }
{ ease: 'steps(10, start)' }

// Spring
import { createSpring } from 'animejs';
{
  ease: createSpring({
    stiffness: 100,
    damping: 10,
    mass: 1,
    velocity: 0
  })
}

// Custom function
{ ease: t => t * t }
```

---

## Utility Functions

```javascript
import {
  $, get, set, remove, sync,
  random, randomPick, shuffle,
  round, clamp, snap, wrap,
  mapRange, lerp, damp,
  degToRad, radToDeg
} from 'animejs';

// DOM utilities
$('.selector');                    // Query selector
get('.el', 'translateX');          // Get value
set('.el', { translateX: 100 });   // Set value
remove('.el');                     // Remove animations

// Math utilities
random(0, 100);                    // Random number
randomPick([1, 2, 3]);             // Random from array
shuffle([1, 2, 3]);                // Shuffle array
round(3.14159, 2);                 // Round to 2 decimals
clamp(value, 0, 100);              // Clamp between min/max
snap(47, 10);                      // Snap to nearest 10 (50)
wrap(370, 0, 360);                 // Wrap to 0-360 (10)
mapRange(0.5, 0, 1, 0, 100);       // Map 0.5 -> 50
lerp(0, 100, 0.5);                 // Linear interp -> 50
degToRad(180);                     // Degrees to radians
radToDeg(Math.PI);                 // Radians to degrees
```

---

## Engine Configuration

```javascript
import { engine } from 'animejs';

// Configure
engine.timeUnit = 's';              // 's' or 'ms'
engine.speed = 1;                   // Global speed
engine.fps = 60;                    // Frame rate limit
engine.precision = 4;               // Decimal precision
engine.pauseOnDocumentHidden = true;

// Methods
engine.update();                    // Manual update
engine.pause();                     // Pause all
engine.resume();                    // Resume all
```

---

## Gotchas

Real bugs hit in practice, verified against actual browser behavior (not just docs) —
worth checking against before assuming a positioning/looping bug is something else.

### An SVG `transform` ATTRIBUTE is silently destroyed by animating `translateX`/`scale`/etc.

Animating `translateX`, `translateY`, `scale`, `rotate`, or any other transform-family
property makes anime.js set a **CSS `transform` property** on the element. A CSS
`transform` property does not compose with an existing SVG `transform` *attribute*
(`<g transform="translate(50,0)">`) — it fully **replaces** it. The instant anime.js
touches the element, the attribute's `translate(50,0)` is gone, and the element's base
position collapses to `(0,0)` while the animation plays a *relative* offset on top of
that zeroed baseline. Symptom: elements fly to the wrong place, overlap, or vanish
outside the viewBox the moment any transform property animates — even though the same
element rendered in exactly the right place before the animation started.

```javascript
// WRONG: base position lives in the transform ATTRIBUTE
// <g id="bar" transform="translate(50,0)"><rect .../></g>
anime.animate('#bar', { translateX: 20 }); // "bar" now animates from x=0, not x=50 —
                                            // the translate(50,0) attribute was wiped.

// RIGHT: base position lives in plain, non-transform attributes (x/cx/y/cy on the
// children); the transform-family property is reserved entirely for anime.js's own
// relative animated offset, so there's nothing for it to collide with.
// <g id="bar"><rect x="50" y="..." .../></g>
anime.animate('#bar', { translateX: 20 }); // moves 20px right of its real x="50" spot
```

If the element also needs to *scale* in place, add
`style="transform-box: fill-box; transform-origin: center"` — without it, `scale`
transforms around the SVG viewport's `(0,0)` origin (not the element's own visual
center), which throws it toward/past the edge of the viewBox on any noticeable scale.

### SVG has no `z-index` — a travelling marker drawn last covers every label it passes

A classic "token flows through the pipeline" animation puts a moving `<circle>` on a
connector between cards. If that circle is appended to the SVG **after** the cards, it
paints **on top of them**, so it sits over each card's title/description text as it
passes — the animation reads as a dot smearing across the words instead of a token
sliding behind the card. `z-index` does not fix this: it has no effect on SVG elements.
**Document order IS paint order**, and it is the only control you have.

```javascript
// WRONG: marker emitted after the boxes -> it paints over their text
svg += connectorLines + boxesWithLabels;
svg += '<circle class="token" .../>';       // covers every label it travels over

// RIGHT: structure first, marker next, boxes last -> the boxes' opaque fill
// occludes the marker, so it reads as passing BEHIND each card
svg += connectorLines;
svg += '<circle class="token" .../>';
svg += boxesWithLabels;                     // painted last = on top of the token
```

Two things make this fail even with the right order:

1. **The card must be opaque.** If the box `<rect>` is semi-transparent (a reveal that
   starts at `opacity: .25`, or a `fill` with alpha), the marker ghosts through it. When
   the boxes fade in as the marker advances, make each box reach full opacity *before*
   the marker arrives at it, not after.
2. **A label that must stay readable goes after everything**, including the marker and
   the boxes — authored prose is not diagram structure, and it should never be occluded.

The general rule for this family of diagrams: **connectors → travelling marker → boxes →
labels.**

### Absolute (non-returning) keyframe values compound across `loop: true`

`.add(target, { translateX: 54 })` animates *to* `54` starting from whatever the
element's current transform value is when that step runs — not from a fixed `0`. On
the first iteration of a loop this looks correct (it starts from the untouched base
state), but from the second iteration on, the element is already sitting at `54` from
the previous lap, so the "same" step now animates from `54` toward `54` (a no-op) or
drifts further if any other step nudges it — loops visibly break after the first
repetition even though a single non-looping playthrough looked perfect.

If a step is meant to reach a new resting value and **stay there** (e.g. a swap that
should look like a real, sticky reorder) rather than bounce back every loop, don't
"fix" this by turning it into a `[from, to, from]` keyframe — that makes the *visual
result* wrong (the swap undoes itself and looks like nothing happened). Instead, let it
land on its real end value, then use `tl.set(targets, { translateX: 0, scale: 1, ... })`
(an instant, non-animated reset — see Timeline Methods above) as the **last** step of
the timeline, so every property is explicitly snapped back to its starting value right
before `loop` restarts the whole sequence from a known-clean state.

### Verify time-position tokens empirically if in doubt

`'<'` = start together with the previous step, `'>'` = end of the previous step (see
the Time Position table above) — but multiple online sources (including older anime.js
v3 material, where the token meanings were sometimes described differently) disagree on
these, and it's cheap to get backwards. If a sequenced timeline looks like steps are
firing out of order or overlapping incorrectly, don't just re-read documentation that
already looked authoritative once — seek the timeline (`tl.seek(ms)` in a loop) and log
`onBegin`/`onComplete` timestamps directly to confirm what a given position token
actually does in the installed version, rather than trusting a remembered or
conflicting written description a second time.
```
