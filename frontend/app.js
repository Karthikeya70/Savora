const log        = document.getElementById("chat-log");
const form       = document.getElementById("chat-form");
const input      = document.getElementById("chat-input");
const statusLine = document.getElementById("status-line");
const llmFlag    = document.getElementById("llm-flag");
const dishCount  = document.getElementById("dish-count");
const newChatBtn = document.getElementById("new-chat-btn");

// Modal elements
const orderModal      = document.getElementById("order-modal");
const modalItems      = document.getElementById("modal-items");
const modalTotal      = document.getElementById("modal-total");
const modalName       = document.getElementById("modal-name");
const modalTable      = document.getElementById("modal-table");
const modalNote       = document.getElementById("modal-note");
const modalCancelBtn  = document.getElementById("modal-cancel-btn");
const modalCloseBtn   = document.getElementById("modal-close-btn");
const modalConfirmBtn = document.getElementById("modal-confirm-btn");

const HISTORY_KEY = "savora_chat_history";
const SESSION_KEY = "savora_session_id";
const TABLE_KEY   = "savora_table";

// Pre-fill table number from QR code link (?table=7)
const _qrTable = new URLSearchParams(location.search).get("table");
if (_qrTable) sessionStorage.setItem(TABLE_KEY, _qrTable);

let history     = JSON.parse(sessionStorage.getItem(HISTORY_KEY) || "[]");
let sessionId   = sessionStorage.getItem(SESSION_KEY) || null;
let requesting  = false;
let currentCart = [];   // tracks latest cart state for the modal

function saveHistory() { sessionStorage.setItem(HISTORY_KEY, JSON.stringify(history)); }
function saveSession(id) { sessionId = id; sessionStorage.setItem(SESSION_KEY, id); }

// ── markdown renderer (safe subset: **bold**, bullet lines, line breaks) ──────
function renderMarkdown(text) {
  let s = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

  const lines = s.split("\n");
  let inList = false;
  const out = [];
  for (const line of lines) {
    const isBullet = /^[•\-]\s+/.test(line);
    if (isBullet && !inList) { out.push("<ul>"); inList = true; }
    if (!isBullet && inList)  { out.push("</ul>"); inList = false; }
    if (isBullet) {
      out.push(`<li>${line.replace(/^[•\-]\s+/, "")}</li>`);
    } else {
      out.push(line);
    }
  }
  if (inList) out.push("</ul>");

  return out.join("\n")
    .replace(/\n(?!<\/?[uoli])/g, "<br>")
    .replace(/<br>\s*<br>/g, "<br>");
}

// ── interactive element helpers ───────────────────────────────────────────────

// Remove any existing cart widget and success cards — only the latest is live.
function clearCartUI() {
  document.querySelectorAll(".cart-widget, .order-success-card").forEach(el => el.remove());
}

// Direct cart mutation — no LLM, instant update used by the +/- widget buttons.
async function cartUpdate(dishName, newQuantity) {
  if (!sessionId || requesting) return;
  setCartButtonsDisabled(true);
  try {
    const res = await fetch("/api/cart/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, dish_name: dishName, quantity: newQuantity }),
    });
    if (!res.ok) return;
    const data = await res.json();
    clearCartUI();
    if (data.cart && data.cart.length > 0) {
      const lastBot = [...document.querySelectorAll(".msg-bot")].at(-1);
      if (lastBot) lastBot.appendChild(renderCartWidget(data.cart, data.cart_total));
    } else {
      currentCart = [];
    }
  } finally {
    setCartButtonsDisabled(false);
  }
}

function setCartButtonsDisabled(disabled) {
  document.querySelectorAll(".qty-btn, .place-order-btn").forEach(btn => {
    btn.disabled = disabled;
  });
}

// ── order confirmation modal ───────────────────────────────────────────────────

function openOrderModal() {
  if (!currentCart.length) return;

  // Populate items
  modalItems.innerHTML = "";
  for (const item of currentCart) {
    const row = document.createElement("div");
    row.className = "modal-item-row";

    const info = document.createElement("div");
    info.className = "modal-item-info";

    const name = document.createElement("div");
    name.className = "modal-item-name";
    name.textContent = item.dish_name;
    info.appendChild(name);

    const cust = item.customizations || {};
    const custParts = [];
    if (cust.add    && cust.add.length)    custParts.push("+" + cust.add.join(", "));
    if (cust.reduce && cust.reduce.length) custParts.push("-" + cust.reduce.join(", "));
    if (custParts.length) {
      const custDiv = document.createElement("div");
      custDiv.className = "modal-item-cust";
      custDiv.textContent = custParts.join("; ");
      info.appendChild(custDiv);
    }

    const qty = document.createElement("span");
    qty.className = "modal-item-qty";
    qty.textContent = `×${item.quantity}`;

    const price = document.createElement("span");
    price.className = "modal-item-price";
    price.textContent = `₹${item.subtotal}`;

    row.append(info, qty, price);
    modalItems.appendChild(row);
  }

  const total = currentCart.reduce((s, i) => s + i.subtotal, 0);
  modalTotal.textContent = `₹${total}`;
  modalName.value  = "";
  modalTable.value = sessionStorage.getItem(TABLE_KEY) || "";
  modalNote.value  = "";
  orderModal.hidden = false;
  modalName.focus();
}

function closeOrderModal() {
  orderModal.hidden = true;
}

async function confirmOrder() {
  if (!sessionId || !currentCart.length) return;
  modalConfirmBtn.disabled = true;
  modalConfirmBtn.textContent = "Placing…";

  const customerName = modalName.value.trim() || null;
  const tableNumber  = modalTable.value.trim() || null;
  const note         = modalNote.value.trim() || null;

  try {
    const res = await fetch("/api/cart/checkout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id:    sessionId,
        customer_name: customerName,
        table_number:  tableNumber,
        note,
      }),
    });
    const data = await res.json();
    closeOrderModal();

    if (!res.ok) {
      addMessage("bot", `Could not place order: ${data.error || "unknown error"}`);
      return;
    }

    clearCartUI();
    currentCart = [];

    // Build success card
    const successCard = document.createElement("div");
    successCard.className = "order-success-card";

    const rows = [
      ["Order ID", data.order_id.slice(0, 8) + "…"],
      ...(customerName ? [["Name",  customerName]]     : []),
      ...(tableNumber  ? [["Table", `Table ${tableNumber}`]] : []),
      ["Total",   `₹${data.total}`],
      ["Status",  "pending — kitchen notified"],
      ...(note    ? [["Note",  note]]               : []),
    ];

    successCard.innerHTML = `<div class="order-success-title">order confirmed</div>` +
      rows.map(([l, v]) => `<div class="order-success-row"><span>${l}</span><span>${v}</span></div>`).join("");

    // Track order link
    const trackLink = document.createElement("a");
    trackLink.href      = `/order-status.html?order_id=${encodeURIComponent(data.order_id)}`;
    trackLink.target    = "_blank";
    trackLink.className = "track-order-link";
    trackLink.textContent = "Track order status →";
    successCard.appendChild(trackLink);

    // Cancel button
    const cancelBtn = document.createElement("button");
    cancelBtn.className = "cancel-order-btn";
    cancelBtn.textContent = "Cancel Order";
    cancelBtn.onclick = async () => {
      cancelBtn.disabled = true;
      cancelBtn.textContent = "Cancelling…";
      const cr = await fetch("/api/order/cancel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ order_id: data.order_id, session_id: sessionId }),
      });
      const cd = await cr.json();
      cancelBtn.remove();
      trackLink.remove();
      const label = document.createElement("div");
      label.className = "order-cancelled-label";
      label.textContent = cr.ok ? "Order cancelled" : (cd.error || "Could not cancel");
      successCard.appendChild(label);
    };
    successCard.appendChild(cancelBtn);

    const lastBot = [...document.querySelectorAll(".msg-bot")].at(-1);
    if (lastBot) lastBot.appendChild(successCard);

    history.push({
      role: "assistant",
      content: `Order placed. ID: ${data.order_id}. Total: ₹${data.total}. ${customerName ? "Name: " + customerName + "." : ""} ${tableNumber ? "Table: " + tableNumber + "." : ""}`.trim(),
      used_llm: false, filters_applied: [], dish_names: [],
    });
    saveHistory();
    log.scrollTop = log.scrollHeight;
  } finally {
    modalConfirmBtn.disabled = false;
    modalConfirmBtn.textContent = "Confirm & Place Order";
  }
}

// Modal event listeners
modalCancelBtn.addEventListener("click", closeOrderModal);
modalCloseBtn.addEventListener("click", closeOrderModal);
orderModal.addEventListener("click", (e) => { if (e.target === orderModal) closeOrderModal(); });
modalConfirmBtn.addEventListener("click", confirmOrder);
modalName.addEventListener("keydown",  (e) => { if (e.key === "Enter") modalTable.focus(); });
modalTable.addEventListener("keydown", (e) => { if (e.key === "Enter") modalNote.focus(); });
modalNote.addEventListener("keydown",  (e) => { if (e.key === "Enter") confirmOrder(); });


function renderCartWidget(cart, cartTotal) {
  currentCart = cart;   // keep in sync for modal

  const widget = document.createElement("div");
  widget.className = "cart-widget";

  const header = document.createElement("div");
  header.className = "cart-widget-header";
  header.textContent = "your cart";
  widget.appendChild(header);

  const list = document.createElement("div");
  list.className = "cart-items-list";

  for (const item of cart) {
    const row = document.createElement("div");
    row.className = "cart-item-row";

    // Name + customisations
    const info = document.createElement("div");
    info.className = "cart-item-info";

    const name = document.createElement("div");
    name.className = "cart-item-name";
    name.textContent = item.dish_name;
    info.appendChild(name);

    const cust = item.customizations || {};
    const custParts = [];
    if (cust.add    && cust.add.length)    custParts.push("+" + cust.add.join(", "));
    if (cust.reduce && cust.reduce.length) custParts.push("-" + cust.reduce.join(", "));
    if (custParts.length) {
      const custSpan = document.createElement("span");
      custSpan.className = "cart-item-cust";
      custSpan.textContent = custParts.join("; ");
      info.appendChild(custSpan);
    }
    row.appendChild(info);

    // Quantity controls
    const controls = document.createElement("div");
    controls.className = "cart-item-controls";

    const minus = document.createElement("button");
    minus.className = "qty-btn";
    minus.textContent = "−";
    minus.title = item.quantity > 1 ? "Reduce quantity" : "Remove item";
    minus.onclick = () => cartUpdate(item.dish_name, item.quantity - 1);

    const qty = document.createElement("span");
    qty.className = "cart-item-qty";
    qty.textContent = item.quantity;

    const plus = document.createElement("button");
    plus.className = "qty-btn";
    plus.textContent = "+";
    plus.title = "Add one more";
    plus.onclick = () => cartUpdate(item.dish_name, item.quantity + 1);

    const price = document.createElement("span");
    price.className = "cart-item-price";
    price.textContent = `₹${item.subtotal}`;

    controls.append(minus, qty, plus, price);
    row.appendChild(controls);
    list.appendChild(row);
  }
  widget.appendChild(list);

  // Footer: total + place order
  const footer = document.createElement("div");
  footer.className = "cart-footer";

  const total = document.createElement("span");
  total.className = "cart-total-label";
  total.textContent = `Total: ₹${cartTotal}`;

  const placeBtn = document.createElement("button");
  placeBtn.className = "place-order-btn";
  placeBtn.textContent = "Place Order";
  placeBtn.onclick = openOrderModal;

  footer.append(total, placeBtn);
  widget.appendChild(footer);
  return widget;
}

function renderOrderSuccess(data) {
  const card = document.createElement("div");
  card.className = "order-success-card";

  const title = document.createElement("div");
  title.className = "order-success-title";
  title.textContent = "order confirmed";
  card.appendChild(title);

  // Try to pull order_id and total from the answer text if not in data directly.
  // The LLM includes them in the answer; we just show a clean card here.
  const rows = [
    ["Status", "pending — kitchen notified"],
    ["Session", sessionId ? sessionId.slice(0, 8) + "…" : "—"],
  ];
  for (const [label, value] of rows) {
    const row = document.createElement("div");
    row.className = "order-success-row";
    row.innerHTML = `<span>${label}</span><span>${value}</span>`;
    card.appendChild(row);
  }
  return card;
}

// ── chat rendering ────────────────────────────────────────────────────────────
function addMessage(role, text, meta) {
  const wrap = document.createElement("div");
  wrap.className = `msg msg-${role}`;

  const label = document.createElement("div");
  label.className = "msg-label";
  label.textContent = role === "user" ? "YOU" : "SAVORA";
  wrap.appendChild(label);

  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";
  if (role === "bot") {
    bubble.innerHTML = renderMarkdown(text);
  } else {
    bubble.textContent = text;
  }
  wrap.appendChild(bubble);

  if (meta) {
    const metaEl = document.createElement("div");
    metaEl.className = "msg-meta";
    metaEl.innerHTML = meta;
    wrap.appendChild(metaEl);
  }

  log.appendChild(wrap);
  log.scrollTop = log.scrollHeight;
  return wrap;
}

function buildMeta(data) {
  const agent = data.routed_to || data.agent || "";
  const tag   = agent ? ` · ${agent}` : "";
  if (data.used_llm) return `<span class="llm-tag">via AI${tag}</span>`;
  const filters = (data.filters_applied || []).join(" · ");
  return `<span class="rule-tag">instant${filters ? " · " + filters : ""}${tag}</span>`;
}

function renderHistory() {
  log.innerHTML = "";
  if (history.length === 0) {
    addMessage("bot",
      'Ask me anything about the menu — allergens, spice level, diet restrictions, price, ' +
      'or just "what\'s good for a first date?" I\'ll figure it out.'
    );
    return;
  }
  for (const turn of history) {
    if (turn.role === "user") {
      addMessage("user", turn.content);
    } else {
      addMessage("bot", turn.content, buildMeta(turn));
    }
  }
}

// ── API call ──────────────────────────────────────────────────────────────────
// silent=true means the user message was triggered by a cart button — show it
// in chat so the conversation stays coherent, but don't show it as a typed message.
async function ask(question, silent = false) {
  if (!question.trim() || requesting) return;
  requesting = true;

  if (!silent) input.value = "";
  input.disabled = true;
  setCartButtonsDisabled(true);

  addMessage("user", question);

  const thinking = document.createElement("div");
  thinking.className = "msg msg-bot thinking";
  thinking.innerHTML = '<div class="msg-label">SAVORA</div><div class="msg-bubble">thinking<span class="cursor">_</span></div>';
  log.appendChild(thinking);
  log.scrollTop = log.scrollHeight;

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, history, session_id: sessionId }),
    });

    if (res.status === 429) {
      thinking.remove();
      addMessage("bot", "You're sending messages too quickly — please wait a moment and try again.");
      return;
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    thinking.remove();

    // Persist session so cart is tied to this conversation.
    if (data.session_id) saveSession(data.session_id);

    const botMsg = addMessage("bot", data.answer, buildMeta(data));

    // Cart UI — only for order agent responses.
    if (data.agent === "order") {
      clearCartUI();
      if (data.order_placed) {
        botMsg.appendChild(renderOrderSuccess(data));
      } else if (data.cart && data.cart.length > 0) {
        botMsg.appendChild(renderCartWidget(data.cart, data.cart_total));
      }
    }

    history.push({ role: "user", content: question });
    history.push({
      role: "assistant",
      content: data.answer,
      used_llm: data.used_llm,
      filters_applied: data.filters_applied,
      dish_names: data.dish_names,
      routed_to: data.routed_to,
    });
    saveHistory();
  } catch (err) {
    thinking.remove();
    addMessage("bot", "Couldn't reach the server. Make sure it's running and try again.");
  } finally {
    requesting = false;
    input.disabled = false;
    setCartButtonsDisabled(false);
    input.focus();
    log.scrollTop = log.scrollHeight;
  }
}

// ── event listeners ───────────────────────────────────────────────────────────
form.addEventListener("submit", (e) => {
  e.preventDefault();
  ask(input.value.trim());
});

document.querySelectorAll(".chip").forEach((btn) => {
  btn.addEventListener("click", () => ask(btn.dataset.q));
});

newChatBtn.addEventListener("click", () => {
  history = [];
  sessionId = null;
  sessionStorage.removeItem(HISTORY_KEY);
  sessionStorage.removeItem(SESSION_KEY);
  // Keep TABLE_KEY — QR table number persists across new chats at the same table
  renderHistory();
});

// ── server status ─────────────────────────────────────────────────────────────
async function loadHealth() {
  try {
    const res  = await fetch("/api/health");
    const data = await res.json();
    const ready = data.index_ready !== false;
    statusLine.textContent = ready ? "online" : "loading…";
    statusLine.style.color = ready ? "var(--green)" : "var(--yellow)";
    llmFlag.textContent    = data.llm_configured ? "AI: enabled" : "AI: not configured";
    dishCount.textContent  = `${data.dish_count} dishes · ${data.restaurant}`;
  } catch {
    statusLine.textContent = "offline";
    statusLine.style.color = "var(--maroon)";
  }
}

loadHealth();
renderHistory();
