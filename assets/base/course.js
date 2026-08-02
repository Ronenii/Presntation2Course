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

  function start() {
    wireQuizzes();
    wireTerms();
    wireSidebarToggle();
    wireToc();
    wireChrome();
    renderDiagrams();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
