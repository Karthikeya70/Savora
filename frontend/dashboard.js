"use strict";

const STATUSES      = ["pending", "confirmed", "preparing", "ready"];
const HIST_STATUSES = new Set(["completed", "cancelled"]);

const STATUS_LABELS = {
  pending:   "PENDING",
  confirmed: "CONFIRMED",
  preparing: "PREPARING",
  ready:     "READY",
};

const NEXT_ACTION = {
  pending:   { label: "CONFIRM ORDER",   next: "confirmed" },
  confirmed: { label: "START PREPARING", next: "preparing" },
  preparing: { label: "MARK READY",      next: "ready" },
  ready:     { label: "COMPLETE ORDER",  next: "completed" },
};

const CANCEL_ALLOWED = new Set(["pending", "confirmed"]);

// Read dashboard secret from URL: /dashboard.html?secret=YOUR_SECRET
const SECRET = new URLSearchParams(location.search).get("secret") || "";

let lastUpdated    = null;
let evtSource      = null;
let knownPendingIds = new Set();
let firstRender     = true;

// ── auth / URL helpers ────────────────────────────────────────────────────────

function qs(extra = "") {
  const params = new URLSearchParams();
  if (SECRET) params.set("secret", SECRET);
  if (extra)  params.set(...extra.split("="));  // unused currently
  const s = params.toString();
  return s ? "?" + s : "";
}

// Carry the secret across to the insights page so it opens without re-typing it.
if (SECRET) {
  const link = document.getElementById("insights-link");
  if (link) link.href = `/insights.html?secret=${encodeURIComponent(SECRET)}`;
}

// ── SSE connection ────────────────────────────────────────────────────────────

function connectSSE() {
  if (evtSource) evtSource.close();
  evtSource = new EventSource(`/api/orders/stream${qs()}`);

  evtSource.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      if (data.error) { showError(data.error); evtSource.close(); return; }
      renderDashboard(data.orders || []);
      lastUpdated = new Date();
      updateClock();
    } catch { /* skip malformed frame */ }
  };

  evtSource.onerror = () => {
    document.getElementById("last-updated").textContent = "reconnecting…";
    // EventSource auto-reconnects — no manual retry needed
  };
}

function showError(msg) {
  document.getElementById("kanban").innerHTML =
    `<div style="grid-column:1/-1;padding:20px 0;color:#921231;border:1px solid #921231;padding:16px;">
       ${msg || "Unauthorized — open /dashboard.html?secret=YOUR_SECRET"}
     </div>`;
}

// ── status update ─────────────────────────────────────────────────────────────

async function advanceStatus(orderId, newStatus, btn) {
  if (btn) { btn.disabled = true; btn.textContent = "…"; }
  try {
    const res = await fetch(`/api/orders/${orderId}/status${qs()}`, {
      method:  "PATCH",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ status: newStatus }),
    });
    if (!res.ok) {
      const err = await res.json();
      alert(err.error || "Failed to update status");
      if (btn) btn.disabled = false;
    }
    // SSE pushes the updated list within 2 s — no manual reload needed
  } catch {
    if (btn) btn.disabled = false;
  }
}

// ── time helpers ──────────────────────────────────────────────────────────────

function timeAgo(isoStr) {
  if (!isoStr) return "";
  // SQLite stores UTC without "Z" — append it for correct parsing
  const diff = Math.floor((Date.now() - new Date(isoStr + "Z").getTime()) / 1000);
  if (diff < 60)   return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

function updateClock() {
  if (lastUpdated)
    document.getElementById("last-updated").textContent =
      "updated " + lastUpdated.toLocaleTimeString();
}

function playNewOrderChime() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    [880, 660].forEach((freq, i) => {
      const osc  = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.frequency.value = freq;
      const t = ctx.currentTime + i * 0.22;
      gain.gain.setValueAtTime(0, t);
      gain.gain.linearRampToValueAtTime(0.35, t + 0.04);
      gain.gain.exponentialRampToValueAtTime(0.001, t + 0.38);
      osc.start(t);
      osc.stop(t + 0.38);
    });
  } catch { /* AudioContext not available */ }
}

function waitingBadge(createdAt, status) {
  if (!createdAt || !["pending", "confirmed", "preparing"].includes(status)) return "";
  const mins = Math.floor((Date.now() - new Date(createdAt + "Z").getTime()) / 60000);
  const cls  = mins >= 15 ? "wait-urgent" : mins >= 8 ? "wait-warning" : "wait-ok";
  return `<div class="card-wait ${cls}">waiting ${mins}m</div>`;
}

// ── render ────────────────────────────────────────────────────────────────────

function esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function renderCard(order) {
  const action    = NEXT_ACTION[order.status];
  const canCancel = CANCEL_ALLOWED.has(order.status);

  const itemsHtml = (order.items || []).map(item => {
    const cust  = item.customizations || {};
    const parts = [];
    if (cust.add?.length)    parts.push("+" + cust.add.join(", "));
    if (cust.reduce?.length) parts.push("−" + cust.reduce.join(", "));
    const custHtml = parts.length
      ? ` <span class="item-cust">(${esc(parts.join("; "))})</span>` : "";
    return `<div class="card-item">• ${esc(item.dish_name)} ×${item.quantity}${custHtml}</div>`;
  }).join("");

  const noteHtml = order.customer_note
    ? `<div class="card-note">${esc(order.customer_note)}</div>` : "";

  const waitHtml = waitingBadge(order.created_at, order.status);

  const primaryBtn = action
    ? `<button class="card-btn card-btn-primary"
         data-id="${esc(order.id)}" data-next="${action.next}">
         ${action.label}
       </button>` : "";

  const cancelBtn = canCancel
    ? `<button class="card-btn card-btn-cancel"
         data-id="${esc(order.id)}" data-next="cancelled">
         CANCEL ORDER
       </button>` : "";

  return `
    <div class="order-card card-${order.status}">
      <div class="card-id">#${esc(order.id.slice(0, 8))}…</div>
      <div class="card-customer">
        <span class="card-name">${esc(order.customer_name || "Guest")}</span>
        <span class="card-table">Table ${esc(order.table_number || "—")}</span>
      </div>
      ${waitHtml}
      <div class="card-items">${itemsHtml}</div>
      ${noteHtml}
      <div class="card-footer">
        <span class="card-total">₹${order.total_amount}</span>
        <span class="card-time">${timeAgo(order.created_at)}</span>
      </div>
      <div class="card-actions">${primaryBtn}${cancelBtn}</div>
    </div>`;
}

function renderDashboard(orders) {
  // ── New order sound notification ────────────────────────────────────────────
  const currentPendingIds = new Set(orders.filter(o => o.status === "pending").map(o => o.id));
  if (!firstRender && [...currentPendingIds].some(id => !knownPendingIds.has(id))) {
    playNewOrderChime();
  }
  firstRender     = false;
  knownPendingIds = currentPendingIds;

  // ── Kanban columns ──────────────────────────────────────────────────────────
  const kanban = document.getElementById("kanban");
  kanban.innerHTML = STATUSES.map(status => {
    const colOrders = orders.filter(o => o.status === status);
    return `
      <div class="kanban-col">
        <div class="kanban-col-header col-h-${status}">
          <span>${STATUS_LABELS[status]}</span>
          <span class="col-count">${colOrders.length}</span>
        </div>
        <div class="col-cards">
          ${colOrders.length
            ? colOrders.map(renderCard).join("")
            : `<div class="col-empty">empty</div>`}
        </div>
      </div>`;
  }).join("");

  kanban.querySelectorAll(".card-btn").forEach(btn => {
    btn.addEventListener("click", () =>
      advanceStatus(btn.dataset.id, btn.dataset.next, btn)
    );
  });

  // ── History log ─────────────────────────────────────────────────────────────
  const histOrders = orders.filter(o => HIST_STATUSES.has(o.status));
  const histEl     = document.getElementById("history");

  if (histOrders.length) {
    histEl.innerHTML = `
      <div class="history-title">COMPLETED &amp; CANCELLED</div>
      ${histOrders.map(o => `
        <div class="history-row">
          <span class="hist-id">#${esc(o.id.slice(0, 8))}…</span>
          <span class="hist-name">${esc(o.customer_name || "Guest")}</span>
          <span class="hist-table">Table ${esc(o.table_number || "—")}</span>
          <span class="hist-total">₹${o.total_amount}</span>
          <span class="hist-time">${timeAgo(o.created_at)}</span>
          <span class="hist-status hs-${o.status}">${o.status.toUpperCase()}</span>
        </div>`).join("")}`;
    histEl.hidden = false;
  } else {
    histEl.hidden = true;
  }
}

// ── boot ──────────────────────────────────────────────────────────────────────
connectSSE();
setInterval(updateClock, 1000);
