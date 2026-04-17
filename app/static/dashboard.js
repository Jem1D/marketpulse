const reportsList = document.getElementById("reportsList");
const reportsMeta = document.getElementById("reportsMeta");
const tickerFilter = document.getElementById("tickerFilter");
const reportTemplate = document.getElementById("reportCardTemplate");

const effectiveTickersEl = document.getElementById("effectiveTickers");
const userTickersEl = document.getElementById("userTickers");

function formatDate(input) {
  if (!input) {
    return "n/a";
  }
  const date = new Date(input);
  if (Number.isNaN(date.getTime())) {
    return input;
  }
  return date.toLocaleString();
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

async function fetchReports() {
  const ticker = tickerFilter.value.trim().toUpperCase();
  const query = new URLSearchParams({ limit: "40" });
  if (ticker) {
    query.set("ticker", ticker);
  }

  const res = await fetch(`/reports?${query.toString()}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Failed loading reports (${res.status})`);
  }
  return res.json();
}

function renderReports(payload) {
  reportsList.innerHTML = "";

  reportsMeta.textContent = `Showing ${payload.count} recent summaries`;

  if (!payload.reports.length) {
    reportsList.innerHTML = '<p class="muted">No summaries found yet. Let the producers and agent run for a minute.</p>';
    return;
  }

  for (const report of payload.reports) {
    const card = reportTemplate.content.firstElementChild.cloneNode(true);

    const move = Number(report.price_change_pct || 0);
    const moveSign = move >= 0 ? "+" : "";

    card.querySelector(".ticker").textContent = `$${report.ticker}`;
    const moveEl = card.querySelector(".move");
    moveEl.textContent = `${moveSign}${move.toFixed(2)}%`;
    moveEl.classList.add(move >= 0 ? "up" : "down");

    card.querySelector(".summary").textContent = report.summary || "No summary available";

    card.querySelector(".price").textContent = `Price ${Number(report.price || 0).toFixed(2)}`;
    card.querySelector(".news-count").textContent = `${report.news_count || 0} headlines`;
    card.querySelector(".detected").textContent = `Detected ${formatDate(report.detected_at)}`;

    const headlinesEl = card.querySelector(".headlines");
    const headlines = Array.isArray(report.headlines) ? report.headlines : [];
    for (const h of headlines.slice(0, 5)) {
      const li = document.createElement("li");
      li.innerHTML = escapeHtml(h);
      headlinesEl.appendChild(li);
    }

    reportsList.appendChild(card);
  }
}

async function loadReports() {
  reportsMeta.textContent = "Loading reports...";
  try {
    const payload = await fetchReports();
    renderReports(payload);
  } catch (err) {
    reportsMeta.textContent = err.message;
  }
}

async function fetchWatchlist() {
  const res = await fetch("/watchlist", { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Failed loading watchlist (${res.status})`);
  }
  return res.json();
}

function renderChips(container, items, removable, onRemove) {
  container.innerHTML = "";

  if (!items.length) {
    container.innerHTML = '<span class="muted">None</span>';
    return;
  }

  for (const value of items) {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = value;

    if (removable) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.title = `Remove ${value}`;
      btn.textContent = "x";
      btn.addEventListener("click", () => onRemove(value));
      chip.appendChild(btn);
    }

    container.appendChild(chip);
  }
}

async function loadWatchlist() {
  try {
    const payload = await fetchWatchlist();
    renderChips(effectiveTickersEl, payload.effective_tickers || [], false, null);
    renderChips(userTickersEl, payload.user_tickers || [], true, removeTicker);
  } catch (err) {
    console.error(err);
  }
}

async function addTicker(event) {
  event.preventDefault();
  const input = document.getElementById("newTickerInput");
  const ticker = input.value.trim().toUpperCase();
  if (!ticker) {
    return;
  }

  const res = await fetch("/watchlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticker }),
  });

  if (!res.ok) {
    const payload = await res.json().catch(() => ({ detail: "Failed to add ticker" }));
    alert(payload.detail || "Failed to add ticker");
    return;
  }

  input.value = "";
  await loadWatchlist();
  await loadReports();
}

async function removeTicker(ticker) {
  const res = await fetch(`/watchlist/${encodeURIComponent(ticker)}`, { method: "DELETE" });
  if (!res.ok) {
    const payload = await res.json().catch(() => ({ detail: "Failed to remove ticker" }));
    alert(payload.detail || "Failed to remove ticker");
    return;
  }

  await loadWatchlist();
  await loadReports();
}

function wireEvents() {
  document.getElementById("addTickerForm").addEventListener("submit", addTicker);
  document.getElementById("refreshReportsBtn").addEventListener("click", loadReports);
  document.getElementById("refreshWatchlistBtn").addEventListener("click", loadWatchlist);
  document.getElementById("applyFilterBtn").addEventListener("click", loadReports);
  document.getElementById("clearFilterBtn").addEventListener("click", () => {
    tickerFilter.value = "";
    loadReports();
  });
}

wireEvents();
loadReports();
loadWatchlist();

setInterval(loadReports, 30000);
setInterval(loadWatchlist, 45000);
