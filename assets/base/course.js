/* Course behaviour. Stateless on purpose: no scores, so no storage to go stale. */
(function () {
  "use strict";

  function markReady() {
    document.documentElement.setAttribute("data-mermaid-ready", "true");
  }

  /* --- quizzes: immediate feedback, unlimited retries, no scoring ---------- */
  function wireQuizzes() {
    document.querySelectorAll(".quiz").forEach(function (quiz) {
      var answer = quiz.querySelector(".quiz__answer");
      var why = quiz.querySelector(".quiz__why");
      quiz.querySelectorAll(".quiz__option").forEach(function (option) {
        option.addEventListener("click", function () {
          var correct = option.getAttribute("data-correct") === "true";
          quiz.querySelectorAll(".quiz__option").forEach(function (other) {
            other.removeAttribute("data-state");
          });
          option.setAttribute("data-state", correct ? "correct" : "incorrect");
          option.setAttribute("aria-pressed", "true");
          if (answer) { answer.hidden = false; }
          if (why) { why.hidden = false; }
        });
      });
    });
  }

  /* --- glossary terms: click to reveal, one at a time --------------------- */
  function wireTerms() {
    var terms = document.querySelectorAll(".term");
    function closeAll(except) {
      terms.forEach(function (term) {
        if (term === except) { return; }
        var id = term.getAttribute("aria-controls");
        var def = id ? document.getElementById(id) : null;
        if (def && !def.hidden) {
          def.hidden = true;
          term.setAttribute("aria-expanded", "false");
        }
      });
    }
    terms.forEach(function (term) {
      term.addEventListener("click", function (event) {
        event.stopPropagation();
        var id = term.getAttribute("aria-controls");
        var def = id ? document.getElementById(id) : term.parentNode.querySelector(".term__def");
        if (!def) { return; }
        var open = def.hidden;
        closeAll(term);
        def.hidden = !open;
        term.setAttribute("aria-expanded", open ? "true" : "false");
      });
    });
    document.addEventListener("click", function () { closeAll(null); });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") { closeAll(null); }
    });
  }

  /* --- mobile sidebar drawer: off-canvas, toggle/scrim/Escape to close ----- */
  function wireSidebarToggle() {
    var toggle = document.getElementById("sidebar-toggle");
    var sidebar = document.getElementById("sidebar");
    var scrim = document.getElementById("sidebar-scrim");
    if (!toggle || !sidebar || !scrim) { return; }

    function isOpen() { return sidebar.getAttribute("data-open") === "true"; }

    function close() {
      sidebar.removeAttribute("data-open");
      scrim.hidden = true;
      toggle.setAttribute("aria-expanded", "false");
      toggle.focus();
    }

    function open() {
      sidebar.setAttribute("data-open", "true");
      scrim.hidden = false;
      toggle.setAttribute("aria-expanded", "true");
      sidebar.focus();
    }

    toggle.addEventListener("click", function () {
      if (isOpen()) { close(); } else { open(); }
    });
    scrim.addEventListener("click", close);
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && isOpen()) { close(); }
    });
    sidebar.querySelectorAll(".toc a").forEach(function (link) {
      link.addEventListener("click", function () {
        if (isOpen()) { close(); }
      });
    });
  }

  /* --- sidebar: highlight the section being read -------------------------- */
  function wireToc() {
    var links = {};
    document.querySelectorAll(".toc a[href^='#']").forEach(function (link) {
      links[link.getAttribute("href").slice(1)] = link;
    });
    var headings = [].slice.call(document.querySelectorAll(".content h2[id], .content h3[id]"));
    if (!headings.length || typeof IntersectionObserver === "undefined") { return; }

    function activate(id) {
      Object.keys(links).forEach(function (key) {
        links[key].removeAttribute("aria-current");
      });
      if (links[id]) { links[id].setAttribute("aria-current", "true"); }
    }
    var observer = new IntersectionObserver(function (entries) {
      var visible = entries
        .filter(function (e) { return e.isIntersecting; })
        .sort(function (a, b) { return a.boundingClientRect.top - b.boundingClientRect.top; });
      if (visible.length) { activate(visible[0].target.id); }
    }, { rootMargin: "-10% 0px -70% 0px", threshold: 0 });
    headings.forEach(function (h) { observer.observe(h); });
    activate(headings[0].id);
  }

  /* --- light/dark and print ---------------------------------------------- */
  function currentlyDark() {
    var explicit = document.documentElement.getAttribute("data-theme");
    if (explicit) { return explicit === "dark"; }
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  function wireChrome() {
    var toggle = document.getElementById("theme-toggle");
    if (toggle) {
      var sync = function () {
        var dark = currentlyDark();
        toggle.setAttribute("aria-pressed", dark ? "true" : "false");
        toggle.textContent = dark ? "Light mode" : "Dark mode";
      };
      toggle.addEventListener("click", function () {
        document.documentElement.setAttribute("data-theme", currentlyDark() ? "light" : "dark");
        sync();
        renderDiagrams();
      });
      sync();
    }
    var print = document.getElementById("print-pdf");
    if (print) {
      print.addEventListener("click", function () { window.print(); });
    }
  }

  /* --- diagrams ---------------------------------------------------------- */
  function themeVariables() {
    var styles = getComputedStyle(document.documentElement);
    var v = function (name) { return styles.getPropertyValue(name).trim(); };
    return {
      background: v("--color-bg"),
      primaryColor: v("--mermaid-primary"),
      secondaryColor: v("--mermaid-secondary"),
      tertiaryColor: v("--color-surface"),
      primaryTextColor: v("--mermaid-text"),
      primaryBorderColor: v("--mermaid-line"),
      lineColor: v("--mermaid-line"),
      textColor: v("--mermaid-text"),
      fontFamily: v("--font-body")
    };
  }

  function renderDiagrams() {
    var nodes = [].slice.call(document.querySelectorAll(".mermaid"));
    if (!nodes.length || typeof mermaid === "undefined") { markReady(); return; }
    nodes.forEach(function (node) {
      if (!node.hasAttribute("data-source")) {
        node.setAttribute("data-source", node.textContent);
      }
      node.removeAttribute("data-processed");
      node.textContent = node.getAttribute("data-source");
    });
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      theme: "base",
      themeVariables: themeVariables()
    });
    mermaid.run({ nodes: nodes })
      .then(markReady)
      .catch(function () { markReady(); });
  }

  /* --- animate blocks: JSON timeline data driven through anime.js -------- */
  function wireAnimations() {
    if (!window.anime) { return; }
    if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      return; // static fallback markup (already in the page) stays as-is
    }
    document.querySelectorAll(".anim__timeline").forEach(function (island) {
      var data;
      try {
        data = JSON.parse(island.textContent);
      } catch (err) {
        return; // malformed data island: leave the static fallback visible
      }
      var animId = island.getAttribute("data-anim-id");
      var caption = animId
        ? document.querySelector('.anim__caption[data-anim-id="' + animId + '"]')
        : null;
      var tl = anime.createTimeline({ loop: !!data.loop, loopDelay: data.loopDelay || 0 });
      (data.steps || []).forEach(function (step) {
        // A plain {x, y} state object is tweened rather than the marker's cx/cy
        // directly (anime.js CAN animate SVG attributes) because the trail is not
        // a tween at all: its "d" must ACCUMULATE an "L x,y" command per frame, so
        // onUpdate needs the live interpolated coordinates as numbers. Reading them
        // off a state object gives both the marker position and the trail growth
        // from a single animation.
        if (step.kind === "path-segment") {
          var marker = document.querySelector(step.marker);
          var trail = document.querySelector(step.trail);
          var state = { x: step.from[0], y: step.from[1] };
          var stepCaption = step.caption;
          var fromX = step.from[0];
          var fromY = step.from[1];
          var segment = {
            duration: step.duration,
            ease: step.ease,
            // Explicit [from, to] pairs rather than bare targets: the tween must
            // start from this segment's own origin on EVERY loop iteration, not
            // from wherever the shared state object was left by the previous lap.
            x: [fromX, step.to[0]],
            y: [fromY, step.to[1]],
            onBegin: function () {
              state.x = fromX;
              state.y = fromY;
              if (stepCaption && caption) { caption.textContent = stepCaption; }
            },
            onUpdate: function () {
              if (marker) {
                marker.setAttribute("cx", state.x);
                marker.setAttribute("cy", state.y);
              }
              if (trail) {
                trail.setAttribute("d", trail.getAttribute("d") + " L " + state.x + "," + state.y);
              }
            },
          };
          if (step.position) {
            tl.add(state, segment, step.position);
          } else {
            tl.add(state, segment);
          }
          return;
        }
        // Instant attribute write for a non-interpolatable value: the trail's "d"
        // is a path-data string ("M 0,10"), so it is assigned outright rather than
        // routed through tl.set()'s tween machinery.
        //
        // It must be SCHEDULED on the timeline (a zero-duration step whose onBegin
        // does the write), not executed here during wiring. Writing it inline would
        // run it exactly once at page load, so on a looping timeline the trail's
        // "d" -- which grows by one "L x,y" per frame -- would never rewind and
        // would instead accumulate without bound across every lap.
        if (step.kind === "set-attr") {
          var attrTargets = step.targets || [];
          var attrProps = step.props || {};
          tl.add({}, {
            duration: 0,
            onBegin: function () {
              attrTargets.forEach(function (selector) {
                var el = document.querySelector(selector);
                if (!el) { return; }
                Object.keys(attrProps).forEach(function (attr) {
                  el.setAttribute(attr, attrProps[attr]);
                });
              });
            },
          });
          return;
        }
        var props = {};
        Object.keys(step.props || {}).forEach(function (key) { props[key] = step.props[key]; });
        if (step.duration != null) { props.duration = step.duration; }
        if (step.ease) { props.ease = step.ease; }
        if (step.caption && caption) {
          props.onBegin = function () { caption.textContent = step.caption; };
        }
        if (step.kind === "set") {
          tl.set(step.targets, props);
        } else if (step.position) {
          tl.add(step.targets, props, step.position);
        } else {
          tl.add(step.targets, props);
        }
      });
    });
  }

  function start() {
    wireQuizzes();
    wireTerms();
    wireSidebarToggle();
    wireToc();
    wireChrome();
    renderDiagrams();
    wireAnimations();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
