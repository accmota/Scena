/* Scena tutorial engine — line-diff, copy-new, step nav, prose blocks
   (`body` / `after` with `{snip}` fragments), note pins, folded old lines. */

const KW = new Set([
  "from", "import", "def", "if", "return", "lambda", "and", "or", "not",
  "True", "False", "None", "in", "for", "while", "else", "elif", "as",
  "class", "pass", "with",
]);

const API = new Set([
  "init", "run", "Circle", "Rect", "Square", "Ellipse", "Line",
  "Triangle", "RegularPolygon", "Polygon", "Point", "Anchor",
  "Sprite", "Wallpaper",
  "Halo", "Neon", "Aura", "Flame", "Metal", "Sphere", "Gel", "ElectricBolt",
  "Shield", "Aurora", "Wave", "Bolt", "DashRing", "ElectricField",
  "Gradient", "keyp", "mouse", "clock", "choice", "uniform", "move_by", "rotate_by",
  "Text", "group", "every", "collide", "destroy", "flash", "pop", "after", "untag",
  "ANYTHING", "intersection", "intersections", "middle_point",
  "show_handles", "no_handles", "set_color",
  "Slider", "Button", "CheckBox", "DropDown", "ui", "chase", "approach",
  "Plasma", "Grain", "MotionTrail", "Color",
  "Sheet", "SkyGradient", "Stars", "Vignette", "Bloom", "Crt", "Scanlines",
  "confine", "ready", "scale_to", "rotate_to", "burst_at", "explosion_at", "inset",
  "Contrail", "Beat", "Menu", "Palette",
]);

function esc(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function highlight(line) {
  const out = [];
  let i = 0;
  const n = line.length;
  while (i < n) {
    if (line[i] === "#") {
      out.push(`<span class="tok-cmt">${esc(line.slice(i))}</span>`);
      break;
    }
    if (line[i] === "@") {
      let j = i + 1;
      while (j < n && /[A-Za-z0-9_]/.test(line[j])) j++;
      out.push(`<span class="tok-dec">${esc(line.slice(i, j))}</span>`);
      i = j;
      continue;
    }
    if (line[i] === '"' || line[i] === "'") {
      const q = line[i];
      let j = i + 1;
      while (j < n && line[j] !== q) {
        if (line[j] === "\\") j++;
        j++;
      }
      out.push(`<span class="tok-str">${esc(line.slice(i, Math.min(j + 1, n + 1)))}</span>`);
      i = j < n ? j + 1 : n;
      continue;
    }
    if (/[A-Za-z_]/.test(line[i])) {
      let j = i + 1;
      while (j < n && /[A-Za-z0-9_]/.test(line[j])) j++;
      const w = line.slice(i, j);
      let cls = "";
      if (KW.has(w)) cls = "tok-kw";
      else if (API.has(w)) cls = "tok-api";
      out.push(cls ? `<span class="${cls}">${esc(w)}</span>` : esc(w));
      i = j;
      continue;
    }
    if (/[0-9]/.test(line[i])) {
      let j = i + 1;
      while (j < n && /[0-9.]/.test(line[j])) j++;
      out.push(`<span class="tok-num">${esc(line.slice(i, j))}</span>`);
      i = j;
      continue;
    }
    out.push(esc(line[i]));
    i++;
  }
  return out.join("");
}

function diffMarks(prev, curr) {
  const a = prev.split("\n");
  const b = curr.split("\n");
  if (!prev) return b.map((line) => (line.trim() === "" ? "old" : "new"));
  const n = a.length;
  const m = b.length;
  const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const marks = [];
  let i = 0;
  let j = 0;
  while (j < m) {
    if (i < n && a[i] === b[j]) {
      marks.push("old");
      i++;
      j++;
    } else if (i < n && (j === m || dp[i + 1][j] >= dp[i][j + 1])) {
      i++;
    } else {
      marks.push("new");
      j++;
    }
  }
  return marks.map((kind, idx) => (b[idx].trim() === "" ? "old" : kind));
}

// A reading step (`focus`) keeps the script and lights the paragraphs that
// start with each anchor (a line prefix, indentation ignored), up to a blank line.
function focusMarks(code, anchors) {
  const lines = code.split("\n");
  const marks = lines.map(() => "old");
  for (const anchor of anchors) {
    let i = lines.findIndex((line) => line.trimStart().startsWith(anchor));
    if (i < 0) console.warn(`focus: no line starts with ${anchor}`);
    for (; i >= 0 && i < lines.length && lines[i].trim() !== ""; i++) marks[i] = "focus";
  }
  return marks;
}

function newSnippet(lines, marks) {
  const hunks = [];
  let buf = [];
  const flush = () => {
    if (buf.length) {
      hunks.push(buf.join("\n"));
      buf = [];
    }
  };
  for (let i = 0; i < lines.length; i++) {
    if (marks[i] === "new") buf.push(lines[i]);
    else flush();
  }
  flush();
  return hunks.join("\n\n");
}

async function copyText(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
  if (!btn) return;
  const prev = btn.textContent;
  btn.textContent = "copiado";
  btn.classList.add("ok");
  setTimeout(() => {
    btn.textContent = prev;
    btn.classList.remove("ok");
  }, 1400);
}

function slugify(title, i) {
  const s = title
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  return s || `passo-${i + 1}`;
}

// The note pins: line index → pin numbers. A note's `at` is a piece of one
// line of the code ("340 * dt"); its pin goes at the end of that line.
function notePins(lines, notes) {
  const pins = new Map();
  (notes || []).forEach((note, k) => {
    const i = lines.findIndex((line) => line.includes(note.at));
    if (i < 0) {
      console.warn(`notes: no line has ${note.at}`);
      return;
    }
    if (!pins.has(i)) pins.set(i, []);
    pins.get(i).push(k + 1);
  });
  return pins;
}

// A pinned line, highlighted with each note's `at` marked: the reader sees
// which piece of the line the balloon is about.
function markNotes(line, nums, notes) {
  const spans = nums
    .map((n) => ({ n, at: notes[n - 1].at, i: line.indexOf(notes[n - 1].at) }))
    .filter((s) => s.i >= 0)
    .sort((a, b) => a.i - b.i);
  let out = "";
  let pos = 0;
  for (const s of spans) {
    if (s.i < pos) continue; // overlaps the previous mark
    out += highlight(line.slice(pos, s.i));
    out += `<span class="mark" data-mark="${s.n}">${highlight(s.at)}</span>`;
    pos = s.i + s.at.length;
  }
  return out + highlight(line.slice(pos));
}

// In a long script, a run of old lines far from what changed folds into one
// row the reader can open ("··· 18 linhas iguais").
const FOLD_MIN_SCRIPT = 30;
const FOLD_MIN_RUN = 8;
const FOLD_CONTEXT = 2;

function foldRuns(lines, marks, pins) {
  if (lines.length < FOLD_MIN_SCRIPT) return [];
  const anchor = lines.map((_, i) => marks[i] !== "old" || pins.has(i));
  if (!anchor.some(Boolean)) return [];
  const keep = anchor.map((_, i) => {
    for (let d = -FOLD_CONTEXT; d <= FOLD_CONTEXT; d++) if (anchor[i + d]) return true;
    return false;
  });
  const runs = [];
  for (let i = 0; i < lines.length; ) {
    if (keep[i]) {
      i++;
      continue;
    }
    let j = i;
    while (j < lines.length && !keep[j]) j++;
    if (j - i >= FOLD_MIN_RUN) runs.push([i, j]);
    i = j;
  }
  return runs;
}

function renderCode(code, marks, reading, notes) {
  const lines = code.split("\n");
  // drop a trailing empty line for display if the source ends with \n
  if (lines.length && lines[lines.length - 1] === "") lines.pop();
  const pins = notePins(lines, notes);
  const folds = foldRuns(lines, marks, pins);
  const row = (line, i) => {
    const kind = marks[i] || "new";
    const nums = pins.get(i) || [];
    const src = line.length ? markNotes(line, nums, notes) : "\n";
    // The pins sit at the right edge of the box, sticky, so the end of a
    // long line scrolled out of view still shows them.
    const tags = nums.length
      ? `<span class="pins">${nums.map((n) => `<span class="pin" data-pin="${n}">${n}</span>`).join("")}</span>`
      : "";
    const pinned = nums.length ? ` pinned" data-pins="${nums.join(" ")}` : "";
    return `<div class="line ${kind}${pinned}"><span class="ln">${i + 1}</span><span class="src">${src}</span>${tags}</div>`;
  };
  const out = [];
  let i = 0;
  for (const [a, b] of folds) {
    for (; i < a; i++) out.push(row(lines[i], i));
    const hidden = lines.slice(a, b).map((line, k) => row(line, a + k)).join("");
    out.push(`<div class="fold"><button type="button" class="fold-btn" data-fold>··· ${b - a} linhas iguais ···</button><div class="fold-body" hidden>${hidden}</div></div>`);
    i = b;
  }
  for (; i < lines.length; i++) out.push(row(lines[i], i));
  const rows = out.join("");
  return `
    <div class="code-panel">
      <div class="code-bar">
        <div class="code-actions">
          <button type="button" class="ghost-btn" data-copy-all>script inteiro</button>
          ${reading ? "" : `<button type="button" class="copy-btn" data-copy-new>copiar trecho novo</button>`}
        </div>
      </div>
      <pre class="code">${rows}</pre>
    </div>`;
}

// The notes under the code: one numbered balloon per pin, in order.
function renderNotes(notes) {
  if (!notes || !notes.length) return "";
  const items = notes
    .map((note, k) => `<li data-note="${k + 1}"><span class="pin">${k + 1}</span><div>${note.text}</div></li>`)
    .join("");
  return `<ol class="notes">${items}</ol>`;
}

// A code fragment inside the prose (`{snip: …}`): highlighted, no line
// numbers, no copy. The whole script below the prose is what gets copied.
// `alt: true` marks a spelling the script does not use (the one to avoid,
// another way to write it): dashed, and the test does not look for it.
function renderSnip(code, alt) {
  const rows = code
    .replace(/\n$/, "")
    .split("\n")
    .map((line) => `<div class="line plain"><span class="src">${line.length ? highlight(line) : "\n"}</span></div>`)
    .join("");
  return `<pre class="code snip${alt ? " alt" : ""}">${rows}</pre>`;
}

// `body` and `after` are HTML, or a list of blocks: HTML strings and
// `{snip: …}` fragments, in reading order.
function renderProse(blocks) {
  if (!blocks) return "";
  const list = Array.isArray(blocks) ? blocks : [blocks];
  return list.map((b) => (typeof b === "string" ? b : renderSnip(b.snip, b.alt))).join("");
}

// A marked piece scrolled out of view (the end of a long line) slides back in,
// clear of the pins at the right edge.
function revealMark(mark) {
  const pre = mark.closest("pre");
  if (!pre) return;
  const box = pre.getBoundingClientRect();
  const r = mark.getBoundingClientRect();
  const pins = mark.closest(".line").querySelector(".pins");
  const right = box.right - (pins ? pins.offsetWidth : 0) - 8;
  const gutter = box.left + 48;
  if (r.right > right) pre.scrollBy({ left: r.right - right, behavior: "smooth" });
  else if (r.left < gutter) pre.scrollBy({ left: r.left - gutter, behavior: "smooth" });
}

// Pointing at a note lights its line, and pointing at a pin lights its note.
function bindNotes(root) {
  const light = (n, on) => {
    root.querySelectorAll(`.pinned`).forEach((line) => {
      if (line.dataset.pins.split(" ").includes(n)) line.classList.toggle("lit", on);
    });
    root.querySelectorAll(`[data-note="${n}"], .pin[data-pin="${n}"], [data-mark="${n}"]`).forEach((el) => el.classList.toggle("lit", on));
    if (on) root.querySelectorAll(`[data-mark="${n}"]`).forEach(revealMark);
  };
  root.querySelectorAll("[data-note], .pin[data-pin], [data-mark]").forEach((el) => {
    const n = el.dataset.note || el.dataset.pin || el.dataset.mark;
    el.addEventListener("mouseenter", () => light(n, true));
    el.addEventListener("mouseleave", () => light(n, false));
  });
  root.querySelectorAll("[data-fold]").forEach((btn) => {
    btn.addEventListener("click", () => {
      btn.nextElementSibling.hidden = false;
      btn.remove();
    });
  });
}

function bindCopy(root, copyNew, copyAll) {
  const newBtn = root.querySelector("[data-copy-new]");
  const allBtn = root.querySelector("[data-copy-all]");
  if (newBtn) newBtn.addEventListener("click", () => copyText(copyNew || copyAll, newBtn));
  if (allBtn) allBtn.addEventListener("click", () => copyText(copyAll, allBtn));
}

function renderAlt(alt, attr, key) {
  const code = alt.code.replace(/\n$/, "");
  const rows = code
    .split("\n")
    .map((line, n) => {
      const src = line.length ? highlight(line) : "\n";
      return `<div class="line new"><span class="ln">${n + 1}</span><span class="src">${src}</span></div>`;
    })
    .join("");
  return `
        <div class="alt">
          ${alt.note ? `<p>${alt.note}</p>` : ""}
          <div class="code-panel">
            <div class="code-bar">
              <button type="button" class="copy-btn" ${attr}="${key}">copiar</button>
            </div>
            <pre class="code">${rows}</pre>
          </div>
        </div>`;
}

function renderTry(items) {
  if (!items || !items.length) return "";
  const blocks = items.map((alt, i) => renderAlt(alt, "data-try", i)).join("");
  return `
    <aside class="try">
      <h2>Experimente também</h2>
      ${blocks}
    </aside>`;
}

// "Para entender melhor": a box that explains the concepts behind a step's
// code (what it is, how it works, the parameters) and may carry alternatives.
function renderDive(items) {
  if (!items || !items.length) return "";
  return items
    .map((item, d) => {
      const alts = (item.try || []).map((alt, i) => renderAlt(alt, "data-dive", `${d}.${i}`)).join("");
      return `
    <aside class="dive">
      <h2>Para entender melhor</h2>
      <h3>${esc(item.title)}</h3>
      <div class="dive-body">${item.body || ""}</div>
      ${alts}
    </aside>`;
    })
    .join("");
}

const Tutorial = {
  mount(cfg) {
    const steps = cfg.steps.map((s, i) => ({
      ...s,
      slug: s.id || slugify(s.title, i),
    }));
    const app = document.getElementById("app");
    const start = hashIndex(steps);

    document.title = `${cfg.title} — Scena`;

    app.innerHTML = `
      <button class="menu-btn" type="button">menu</button>
      <div class="page">
        <aside class="sidebar">
          <div class="brand">
            <a href="index.html">Scena</a>
            <span class="sub">Tutoriais</span>
          </div>
          <div class="tut-label">${esc(cfg.label || "Tutorial")} ${cfg.n || ""}</div>
          <div class="tut-title">${esc(cfg.title)}</div>
          <nav><ol class="steps"></ol></nav>
        </aside>
        <main></main>
      </div>`;

    const ol = app.querySelector(".steps");
    const main = app.querySelector("main");
    const menuBtn = app.querySelector(".menu-btn");

    menuBtn.addEventListener("click", () => document.body.classList.toggle("nav-open"));

    let idx = start;

    function go(i, push) {
      idx = Math.max(0, Math.min(steps.length - 1, i));
      if (push !== false) history.replaceState(null, "", `#${steps[idx].slug}`);
      render();
      window.scrollTo(0, 0);
      document.body.classList.remove("nav-open");
    }

    function render() {
      const step = steps[idx];
      ol.innerHTML = steps
        .map((s, i) => {
          const cls = i === idx ? "active" : i < idx ? "done" : "";
          const head = s.part ? `<li class="part">${esc(s.part)}</li>` : "";
          return `${head}<li><a href="#${s.slug}" class="${cls}" data-i="${i}"><span class="n">${String(i + 1).padStart(2, "0")}</span><span>${esc(s.title)}</span></a></li>`;
        })
        .join("");
      const part = steps.slice(0, idx + 1).reverse().find((s) => s.part);

      const prevCode = step.fresh || idx === 0 ? "" : steps[idx - 1].code;
      const marks = step.focus ? focusMarks(step.code, step.focus) : diffMarks(prevCode, step.code);
      const lines = step.code.replace(/\n$/, "").split("\n");
      const copyNew = newSnippet(lines, marks);
      const copyAll = step.code.replace(/\n$/, "") + "\n";

      const closing = step.closing
        ? `<div class="closing">${step.closing}</div>`
        : "";
      const recap = step.recap
        ? `<aside class="recap"><h2>O que vimos</h2>${step.recap}</aside>`
        : "";

      main.innerHTML = `
        <div class="kicker">${part ? `${esc(part.part)} · ` : ""}Passo ${idx + 1} de ${steps.length}</div>
        <h1>${esc(step.title)}</h1>
        <div class="explain">${renderProse(step.body)}</div>
        ${renderCode(step.code, marks, !!step.focus, step.notes)}
        ${renderNotes(step.notes)}
        ${step.after ? `<div class="explain after">${renderProse(step.after)}</div>` : ""}
        ${renderTry(step.try)}
        ${renderDive(step.dive)}
        ${closing}
        ${recap}
        <div class="step-nav">
          <button type="button" class="nav-btn" data-prev ${idx === 0 ? "disabled" : ""}>← Anterior</button>
          <button type="button" class="nav-btn primary" data-next ${idx === steps.length - 1 ? "disabled" : ""}>Próximo →</button>
        </div>`;

      bindCopy(main, copyNew, copyAll);
      bindNotes(main);
      main.querySelectorAll("[data-try]").forEach((btn) => {
        const alt = step.try[Number(btn.dataset.try)];
        btn.addEventListener("click", () => copyText(alt.code.replace(/\n$/, "") + "\n", btn));
      });
      main.querySelectorAll("[data-dive]").forEach((btn) => {
        const [d, i] = btn.dataset.dive.split(".").map(Number);
        const alt = step.dive[d].try[i];
        btn.addEventListener("click", () => copyText(alt.code.replace(/\n$/, "") + "\n", btn));
      });
      main.querySelector("[data-prev]").addEventListener("click", () => go(idx - 1));
      main.querySelector("[data-next]").addEventListener("click", () => go(idx + 1));
    }

    ol.addEventListener("click", (e) => {
      const a = e.target.closest("a[data-i]");
      if (!a) return;
      e.preventDefault();
      go(Number(a.dataset.i));
    });

    window.addEventListener("hashchange", () => go(hashIndex(steps), false));
    window.addEventListener("keydown", (e) => {
      if (e.target.closest("input, textarea")) return;
      if (e.key === "ArrowRight") {
        e.preventDefault();
        go(idx + 1);
      }
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        go(idx - 1);
      }
    });

    go(start, false);

    function hashIndex(list) {
      const h = decodeURIComponent(location.hash.replace(/^#/, ""));
      if (!h) return 0;
      const bySlug = list.findIndex((s) => s.slug === h);
      if (bySlug >= 0) return bySlug;
      const n = parseInt(h, 10);
      if (n >= 1 && n <= list.length) return n - 1;
      return 0;
    }
  },
};

window.Tutorial = Tutorial;
