"use strict";

/**
 * Insights page.
 *
 * Reads /api/insights and renders it in plain language. Every section says what
 * it means, because a number without its meaning is not an insight.
 *
 * REAL  = source "live": things actual people did in the app.
 * DEMO  = source "demo": pretend customers from scripts/demo_data.py, for
 *         learning to read the page. Never real findings.
 */

const SECRET  = new URLSearchParams(location.search).get("secret") || "";
const STORE   = "savora_insights_source";
const REFRESH = 20000;
const MIN_REAL_VISITORS = 20;   // below this, open on DEMO for first-time viewers

let source = "live";
let timer  = null;
let latest = null;
let sortBy = { key: "times_ordered", dir: -1 };

// ── small helpers ─────────────────────────────────────────────────────────────

function esc(v) {
  return String(v ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/** 0.4633 -> "46%". Null means "nothing to divide by yet". */
function pct(v, dash = "—") {
  return v === null || v === undefined ? dash : Math.round(v * 100) + "%";
}

function ms(v) {
  if (v === null || v === undefined) return "—";
  return v < 1000 ? `${v} ms` : `${(v / 1000).toFixed(1)} s`;
}

function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}

function section(title, help, bodyHtml) {
  return `<section class="section">
            <h2 class="sec-title">${title}</h2>
            <p class="sec-help">${help}</p>
            ${bodyHtml}
          </section>`;
}

// ── sections ──────────────────────────────────────────────────────────────────

function renderTiles(h) {
  const tiles = [
    ["t-customers", "People who used the chat", h.customers,
     `${plural(h.questions, "question", "questions")} asked in total`],
    ["t-ordered", "Ordered afterwards", pct(h.order_rate),
     `${plural(h.orders, "order", "orders")} placed${h.cancelled ? `, ${h.cancelled} cancelled` : ""}`],
    ["t-suggest", "Orders using a suggestion", pct(h.suggestion_share),
     `${h.orders_using_suggestion} of ${h.orders} orders had a dish the assistant named first`],
    ["t-liked", "Liked their food", pct(h.like_rate),
     h.ratings ? `from ${plural(h.ratings, "rating", "ratings")}` : "nobody has rated yet"],
  ];
  return `<div class="tiles">${tiles.map(([cls, label, value, sub]) => `
    <div class="tile ${cls}">
      <span class="tile-label">${label}</span>
      <span class="tile-value">${esc(value)}</span>
      <span class="tile-sub">${esc(sub)}</span>
    </div>`).join("")}</div>`;
}

function renderTrust(h) {
  const bad  = h.invented_feedback;
  const rate = h.invented_feedback_rate;
  const ok   = !bad;
  return `<div class="compare">
      <div class="compare-card ${ok ? "hi" : "warn"}">
        <span class="tile-label">Answers claiming guest opinions with no ratings behind them</span>
        <div class="tile-value" style="color:${ok ? "var(--green)" : "var(--orange)"}">
          ${bad}${h.menu_answers ? ` <span style="font-size:13px;color:var(--gray-light)">of ${h.menu_answers}</span>` : ""}
        </div>
        <span class="tile-sub">${h.menu_answers
          ? (ok ? "None so far. The guardrail is holding." : `${pct(rate)} of menu answers — worth investigating`)
          : "no menu answers yet"}</span>
      </div>
    </div>`;
}

function renderFunnel(funnel) {
  const start = funnel[0]?.customers || 0;
  const rows = funnel.map((f, i) => {
    const prev = i ? funnel[i - 1].customers : null;
    const lost = prev !== null ? prev - f.customers : 0;
    const width = start ? (f.customers / start) * 100 : 0;
    return `
      <div class="bar-line">
        <span class="bar-name">${esc(f.label)}</span>
        <span class="bar-track"><span class="bar-fill" style="width:${width.toFixed(1)}%"></span></span>
        <span class="bar-num"><b>${f.customers}</b> · ${pct(f.share_of_askers)}</span>
      </div>
      ${lost > 0 ? `<div class="bar-line"><span class="drop">↳ ${lost} stopped here</span></div>` : ""}`;
  }).join("");
  return `<div class="bar-list">${rows}</div>`;
}

function renderTopics(topics) {
  if (!topics.length) return `<p class="sec-help muted">No questions yet.</p>`;
  const max = Math.max(...topics.map(t => t.questions));
  return `<div class="bar-list">${topics.map(t => `
    <div class="bar-line">
      <span class="bar-name">${esc(t.label)}</span>
      <span class="bar-track"><span class="bar-fill" style="width:${(t.questions / max * 100).toFixed(1)}%"></span></span>
      <span class="bar-num"><b>${pct(t.share)}</b> · ${t.questions}</span>
    </div>
    <div class="bar-line">
      <span class="drop" style="color:var(--gray-mid)">↳ ${pct(t.went_on_to_order)} of these
        ${t.customers === 1 ? "person" : "people"} ordered · typically ${ms(t.median_response_ms)} to answer</span>
    </div>`).join("")}</div>`;
}

const DISH_COLUMNS = [
  { key: "dish",                  label: "Dish",                  num: false },
  { key: "customers_shown",       label: "People shown it",       num: true  },
  { key: "picked_when_suggested", label: "Picked when shown",     num: true  },
  { key: "times_ordered",         label: "Times ordered",         num: true  },
  { key: "like_rate",             label: "Liked it",              num: true  },
];

function renderDishes(dishes, minRatings) {
  const shown = dishes.filter(d => d.times_suggested || d.times_ordered || d.ratings);
  if (!shown.length) return `<p class="sec-help muted">No dishes have been suggested or ordered yet.</p>`;

  const dir = sortBy.dir;
  shown.sort((a, b) => {
    const av = a[sortBy.key], bv = b[sortBy.key];
    if (typeof av === "string") return av.localeCompare(bv) * dir * -1;
    // Dishes with no rating yet always sit at the bottom, never at the top.
    if (av === null) return 1;
    if (bv === null) return -1;
    return (av - bv) * dir;
  });

  const head = DISH_COLUMNS.map(c => `
    <th class="${c.num ? "num" : ""}">
      <button type="button" data-sort="${c.key}"
        ${sortBy.key === c.key ? `aria-sort="${dir === -1 ? "descending" : "ascending"}"` : ""}>
        ${c.label}${sortBy.key === c.key ? (dir === -1 ? " ↓" : " ↑") : ""}
      </button>
    </th>`).join("");

  const body = shown.map(d => {
    const liked = d.like_rate === null
      ? `<span class="muted">not rated</span>`
      : `<span class="like ${d.low_sample ? "low" : ""} ${d.like_rate < 0.6 ? "bad" : ""}">
           <span class="like-bar"><i style="width:${(d.like_rate * 100).toFixed(0)}%"></i></span>
           <span>${pct(d.like_rate)}</span>
         </span>`;
    const sample = d.ratings
      ? `<span class="pill">${d.ratings}${d.low_sample ? " · few" : ""}</span>`
      : "";
    return `<tr>
      <td>${esc(d.dish)}<span class="cat">${esc(d.category)} · ₹${d.price_inr}</span></td>
      <td class="num">${d.customers_shown || `<span class="muted">0</span>`}</td>
      <td class="num">${pct(d.picked_when_suggested)}</td>
      <td class="num">${d.times_ordered}</td>
      <td class="num">${liked} ${sample}</td>
    </tr>`;
  }).join("");

  return `<div class="table-wrap"><table>
      <thead><tr>${head}</tr></thead>
      <tbody>${body}</tbody>
    </table></div>
    <p class="callout">“Picked when shown” is the share of people who ordered a dish
      after the assistant named it to them. A dish shown often but rarely picked may be
      described badly, priced wrong, or suggested to the wrong people.
      “few” means fewer than ${minRatings} ratings, so treat that % as a hint, not a fact.</p>`;
}

function renderCompare(path, decide) {
  const a = path.suggested, b = path.not_suggested;
  const better = a.like_rate !== null && b.like_rate !== null && a.like_rate > b.like_rate;
  const card = (label, v, hi) => `
    <div class="compare-card ${hi ? "hi" : ""}">
      <span class="tile-label">${label}</span>
      <div class="tile-value" style="color:${hi ? "var(--green)" : "var(--offwhite)"}">${pct(v.like_rate)}</div>
      <span class="tile-sub">${v.ratings ? `from ${plural(v.ratings, "rating", "ratings")}` : "no ratings yet"}</span>
    </div>`;

  const verdict = (a.ratings && b.ratings)
    ? (better
        ? "Right now people like suggested dishes more. Worth watching as more ratings come in."
        : "No advantage so far. If that holds with more ratings, the suggestions aren't earning their place.")
    : "Not enough ratings yet to compare the two.";

  return `<div class="compare">
      ${card("Dish the assistant suggested", a, better)}
      ${card("Dish they chose themselves", b, false)}
    </div>
    <p class="callout"><b>${esc(verdict)}</b></p>
    <p class="callout">People who ordered asked
      <b>${decide.median === null ? "—" : plural(decide.median, "question", "questions")}</b>
      first (typical, across ${plural(decide.customers, "order", "orders")}).
      If that number climbs, deciding is getting harder, not easier.</p>`;
}

function renderGaps(list) {
  if (!list.length) return `<p class="sec-help muted">None — every question found at least one dish.</p>`;
  return `<ul class="qlist">${list.map(q => `
    <li><span class="q">${esc(q.question)}</span><span class="muted">${esc(q.label)}</span></li>`).join("")}</ul>
    <p class="callout">These are things people wanted that the menu couldn't answer.
      Repeats here are the cheapest menu research you will ever get.</p>`;
}

function renderEmpty() {
  return `<div class="empty">
      <b>No real customer activity yet.</b>
      <ol>
        <li>Start the app: <code>python run_local.py</code></li>
        <li>Open the chat, ask a question, add a dish, place an order.</li>
        <li>On the kitchen board, move the order to READY.</li>
        <li>Open the tracking link and rate the dish.</li>
        <li>Come back here — the numbers will appear.</li>
      </ol>
      To see what this page looks like with plenty of data, switch to DEMO above.
    </div>`;
}

// ── page assembly ─────────────────────────────────────────────────────────────

function render(data) {
  latest = data;
  const root   = document.getElementById("root");
  const banner = document.getElementById("banner");

  banner.innerHTML = data.source === "demo"
    ? `<div class="banner"><b>DEMO DATA</b> — pretend customers created by
        scripts/demo_data.py. Use it to learn how to read this page.
        These are not real findings and must never be presented as results.</div>`
    : "";

  if (!data.has_data) {
    root.innerHTML = renderEmpty();
    return;
  }

  root.innerHTML = [
    section("The big picture",
      "Four numbers that say whether the assistant is helping people order food they end up enjoying.",
      renderTiles(data.headline)),
    section("Honesty check",
      "The assistant may only mention what guests thought of a dish once real people have rated it. Every answer is checked automatically, because this failed silently the first time it was built.",
      renderTrust(data.headline)),
    section("Where people drop off",
      "Of everyone who asked a question, how many made it to each next step. The biggest fall is where to look first.",
      renderFunnel(data.funnel)),
    section("What people ask about",
      "Every question sorted into one topic, with how many of those people went on to order, and how long they waited for an answer.",
      renderTopics(data.topics)),
    section("Dish scorecard",
      "How each dish performs at three different moments: being shown, being chosen, and being eaten.",
      renderDishes(data.dishes, data.min_ratings_for_confidence)),
    section("Does the assistant actually help?",
      "Comparing how much people liked dishes the assistant suggested against dishes they picked on their own.",
      renderCompare(data.liked_by_path, data.questions_before_order)),
    section("Questions the menu couldn't answer",
      "The assistant replied but could not point to a single dish. Usually that means the menu is missing something.",
      renderGaps(data.no_dish_questions)),
  ].join("");

  root.querySelectorAll("th button[data-sort]").forEach(btn => {
    btn.addEventListener("click", () => {
      const key = btn.dataset.sort;
      sortBy = { key, dir: sortBy.key === key ? -sortBy.dir : -1 };
      render(latest);
    });
  });

  document.getElementById("updated").textContent = "updated " + new Date().toLocaleTimeString();
}

// ── loading ───────────────────────────────────────────────────────────────────

async function load() {
  const params = new URLSearchParams({ source });
  if (SECRET) params.set("secret", SECRET);
  try {
    const res  = await fetch(`/api/insights?${params}`);
    const data = await res.json();
    if (!res.ok) {
      document.getElementById("banner").innerHTML =
        `<div class="banner error">${esc(data.error || "Could not load insights.")}
         ${res.status === 401 ? "Open this page as /insights.html?secret=YOUR_SECRET" : ""}</div>`;
      document.getElementById("root").innerHTML = "";
      return;
    }
    // Until there are enough real visitors for the numbers to mean anything, a
    // first-time viewer sees the practice data instead. It is clearly labelled
    // DEMO, the viewer can switch to REAL any time, and the choice isn't saved.
    if (!viewerChose && data.source === "live" && data.headline.customers < MIN_REAL_VISITORS) {
      setSource("demo", false);
      return;
    }
    render(data);
  } catch {
    document.getElementById("banner").innerHTML =
      `<div class="banner error">Could not reach the server. Is it running?</div>`;
  }
}

// True once the viewer has picked REAL or DEMO themselves.
let viewerChose = false;

function setSource(next, remember = true) {
  source = next;
  if (remember) {
    viewerChose = true;
    try { localStorage.setItem(STORE, next); } catch { /* private mode */ }
  }
  document.querySelectorAll(".toggle button").forEach(b =>
    b.setAttribute("aria-pressed", String(b.dataset.source === next)));
  load();
}

document.querySelectorAll(".toggle button").forEach(btn =>
  btn.addEventListener("click", () => setSource(btn.dataset.source)));

if (SECRET) {
  document.getElementById("kitchen-link").href =
    `/dashboard.html?secret=${encodeURIComponent(SECRET)}`;
}

let saved = null;
try { saved = localStorage.getItem(STORE); } catch { /* private mode */ }
viewerChose = saved === "demo" || saved === "live";
setSource(saved === "demo" ? "demo" : "live", false);
timer = setInterval(load, REFRESH);
