const CHECKS = {luecken: "Lücken", widersprueche: "Widersprüche", allergene: "Allergene", claims: "Claims"};
const STATUS = {red: "Rot", yellow: "Gelb", green: "Grün"};
const NUTRIENTS = {"energy-kcal_100g": "Energie (kcal)", fat_100g: "Fett", "saturated-fat_100g": "davon gesättigt",
  carbohydrates_100g: "Kohlenhydrate", sugars_100g: "davon Zucker", proteins_100g: "Eiweiß", salt_100g: "Salz"};
const SOURCES = {brand: "Stahlkern", off: "Open Food Facts"};
const state = {source: "brand", status: "all", check: "all", q: "", data: null};

const $ = (id) => document.getElementById(id);
function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v; else if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v); else e.setAttribute(k, v);
  }
  kids.forEach((c) => e.append(c));
  return e;
}
const fmt = (n) => new Intl.NumberFormat("de-DE").format(n);
const dot = (s) => el("span", {class: "dot " + s, title: STATUS[s]});

function sourceChips() {
  const box = $("sourceFilter");
  box.replaceChildren();
  for (const [value, label] of Object.entries(SOURCES)) {
    const n = state.data.results.filter((r) => r.source === value).length;
    box.append(el("button", {class: "chip", "aria-pressed": String(state.source === value), text: `${label} (${n})`,
      onclick: () => { state.source = value; sourceChips(); renderStats(state.data.meta); render(); }}));
  }
}

function chips(box, items, key) {
  box.replaceChildren();
  for (const [value, label] of items) {
    box.append(el("button", {class: "chip", "aria-pressed": String(state[key] === value), text: label,
      onclick: () => { state[key] = value; chips(box, items, key); render(); }}));
  }
}

function sourceRows() { return state.data.results.filter((r) => r.source === state.source); }

function renderStats(meta) {
  const rows = sourceRows();
  const c = {red: 0, yellow: 0, green: 0};
  rows.forEach((r) => { c[r.status] += 1; });
  $("claim").replaceChildren(
    `${fmt(meta.products)} Produkte geprüft, `, el("b", {text: "0 € API Kosten"}),
    `, ${fmt(meta.llm_minutes)} Minuten lokal.`);
  const items = [
    [fmt(rows.length), "Produkte in dieser Quelle"], [fmt(c.red), "rot"], [fmt(c.yellow), "gelb"], [fmt(c.green), "grün"],
    ["0 €", "API Kosten"], [fmt(meta.llm_minutes) + " Min.", "Laufzeit lokal, Modell " + meta.model],
    [fmt(meta.tokens_in + meta.tokens_out), "Token gesamt"],
  ];
  $("stats").replaceChildren(...items.map(([n, l]) =>
    el("div", {class: "stat"}, el("div", {class: "n", text: n}), el("div", {class: "l", text: l}))));
}

function visible() {
  const q = state.q.trim().toLowerCase();
  return sourceRows().filter((r) =>
    (state.status === "all" || r.status === state.status) &&
    (state.check === "all" || r.checks[state.check] !== "green") &&
    (!q || (r.name + " " + r.brand).toLowerCase().includes(q)));
}

function render() {
  const rows = visible();
  $("count").textContent = `${rows.length} von ${sourceRows().length} Produkten`;
  $("list").replaceChildren(...rows.map((r) => {
    const row = el("li", {class: "row", tabindex: "0", role: "button", onclick: () => openDetail(r),
      onkeydown: (e) => { if (e.key === "Enter") openDetail(r); }},
      dot(r.status),
      el("div", {}, el("div", {class: "name", text: r.name}), el("div", {class: "brand", text: r.brand || "ohne Marke"})),
      el("div", {class: "mini"}, ...Object.keys(CHECKS).map((k) => dot(r.checks[k]))),
      el("div", {class: "time", text: r.llm.cached ? "Cache" : r.llm.seconds + " s"}));
    return row;
  }));
}

function openDetail(r) {
  const body = $("detailBody");
  body.replaceChildren(el("h2", {text: r.name}),
    el("p", {class: "muted", text: `${r.brand || "ohne Marke"} · ${r.source === "brand" ? "Art. Nr." : "EAN"} ${r.code}`}));
  for (const [key, label] of Object.entries(CHECKS)) {
    const fs = r.findings.filter((f) => f.check === key);
    body.append(el("h3", {text: label}));
    if (!fs.length) { body.append(el("p", {class: "muted", text: "Keine Funde."})); continue; }
    for (const f of fs) {
      const box = el("div", {class: "finding " + (f.severity === "error" ? "red" : "yellow")},
        el("div", {text: f.message}));
      if (f.replacement) box.append(el("div", {class: "fix"}, el("span", {text: "Korrekturvorschlag"}),
        el("div", {text: f.replacement})));
      body.append(box);
    }
  }
  if (r.llm.error) body.append(el("p", {class: "muted", text: "Modellfehler: " + r.llm.error}));
  body.append(el("h3", {text: "KI Lauf"}), table([
    ["Modell", `${r.llm.model} (${r.llm.mode})`], ["Laufzeit", r.llm.seconds + " s"],
    ["Token (Prompt / Antwort)", `${fmt(r.llm.tokens_in)} / ${fmt(r.llm.tokens_out)}`],
    ["API Kosten", "0 €"], ["Aus Cache", r.llm.cached ? "ja" : "nein"]]));
  const n = r.product.nutriments || {};
  body.append(el("h3", {text: "Nährwerte pro 100 g"}), table(Object.entries(NUTRIENTS).map(
    ([k, l]) => [l, n[k] === undefined ? "fehlt" : String(n[k])])));
  if (r.product.description) body.append(el("h3", {text: "Produkttext"}), el("p", {text: r.product.description}));
  body.append(el("h3", {text: "Zutaten"}), el("p", {text: r.product.ingredients || "fehlt"}));
  if (r.source === "off" && r.product.url) body.append(el("p", {}, el("a", {href: r.product.url, text: "Eintrag bei Open Food Facts"})));
  $("detail").hidden = false;
  $("detail").scrollTop = 0;
}
const table = (rows) => el("table", {}, ...rows.map(([a, b]) => el("tr", {}, el("td", {text: a}), el("td", {text: b}))));

$("close").onclick = () => { $("detail").hidden = true; };
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("detail").hidden = true; });
$("search").oninput = (e) => { state.q = e.target.value; render(); };

fetch("public/results.json").then((r) => r.json()).then((data) => {
  state.data = data;
  $("placeholder").hidden = !data.meta.placeholder;
  renderStats(data.meta);
  sourceChips();
  chips($("statusFilter"), [["all", "Alle"], ...Object.entries(STATUS)], "status");
  chips($("checkFilter"), [["all", "Alle Prüfungen"], ...Object.entries(CHECKS)], "check");
  render();
}).catch(() => { $("count").textContent = "results.json nicht gefunden. Zuerst make check-all ausführen."; });
