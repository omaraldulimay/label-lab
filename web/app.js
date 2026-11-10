const I18N = {
  de: {
    eyebrow: "Produktdaten Check", search: "Produkt oder Marke suchen", searchlabel: "Suche", source: "Quelle",
    light: "Ampel", checktype: "Prüfungsart", close: "Schließen",
    placeholder: "Platzhalter: Diese Ergebnisse stammen aus dem Fake Modus, die Claim Funde sind nicht von einem echten Modell.",
    foot1: "Die Quelle Open Food Facts: Produktdaten von <a href=\"https://world.openfoodfacts.org\">Open Food Facts</a>, Lizenz <a href=\"https://opendatacommons.org/licenses/odbl/1-0/\">ODbL</a>. Eine Zusammenstellung der Daten bleibt unter ODbL.",
    foot2: "Regeln laufen in Python, ein lokales Modell prüft nur die Sprache der Werbeaussagen.",
    brandSource: "RAWFORM", offSource: "Open Food Facts", noBrand: "ohne Marke",
    luecken: "Lücken", widersprueche: "Widersprüche", allergene: "Allergene", claims: "Claims",
    red: "Rot", yellow: "Gelb", green: "Grün", all: "Alle", allChecks: "Alle Prüfungen",
    checked: (n) => `${n} Produkte geprüft, `, cost: "0 € API Kosten", localMin: (n) => `, ${n} Minuten lokal.`,
    statProducts: "Produkte in dieser Quelle", statRed: "rot", statYellow: "gelb", statGreen: "grün",
    statCost: "API Kosten", statRuntime: (m) => `Laufzeit lokal, Modell ${m}`, statTokens: "Token gesamt",
    count: (a, b) => `${a} von ${b} Produkten`, noResults: "results.json nicht gefunden. Zuerst make check-all ausführen.",
    artNo: "Art. Nr.", ean: "EAN", noFindings: "Keine Funde.", rule: "Rechtsgrundlage", suggestion: "Korrekturvorschlag",
    apply: "Korrektur übernehmen", applied: "Übernommen", reset: "Zurücksetzen", was: (s) => `vorher ${s}`,
    resetHint: "Änderungen nur im Browser.", modelError: "Modellfehler: ",
    llmRun: "KI Lauf", model: "Modell", runtime: "Laufzeit", tokens: "Token (Prompt / Antwort)", apiCost: "API Kosten",
    cache: "Aus Cache", yes: "ja", no: "nein", cacheShort: "Cache", nutrients: "Nährwerte pro 100 g", missing: "fehlt",
    productText: "Produkttext (Deutsch)", ingredients: "Zutaten", offLink: "Eintrag bei Open Food Facts",
    fieldName: "Name", fieldGeneric: "Bezeichnung", fieldLabels: "Hinweise", fieldDescription: "Beschreibung",
    n_energy: "Energie (kcal)", n_fat: "Fett", n_sat: "davon gesättigt", n_carbs: "Kohlenhydrate",
    n_sugars: "davon Zucker", n_protein: "Eiweiß", n_salt: "Salz",
    locale: "de-DE",
  },
  en: {
    eyebrow: "Product data check", search: "Search product or brand", searchlabel: "Search", source: "Source",
    light: "Traffic light", checktype: "Check type", close: "Close",
    placeholder: "Placeholder: these results come from the fake mode, the claim findings are not from a real model.",
    foot1: "The source Open Food Facts: product data from <a href=\"https://world.openfoodfacts.org\">Open Food Facts</a>, licence <a href=\"https://opendatacommons.org/licenses/odbl/1-0/\">ODbL</a>. A compilation of the data stays under ODbL.",
    foot2: "Rules run in Python, a local model only checks the wording of the advertising claims. Product texts stay in German.",
    brandSource: "RAWFORM", offSource: "Open Food Facts", noBrand: "no brand",
    luecken: "Gaps", widersprueche: "Contradictions", allergene: "Allergens", claims: "Claims",
    red: "Red", yellow: "Yellow", green: "Green", all: "All", allChecks: "All checks",
    checked: (n) => `${n} products checked, `, cost: "€0 API cost", localMin: (n) => `, ${n} minutes local.`,
    statProducts: "products in this source", statRed: "red", statYellow: "yellow", statGreen: "green",
    statCost: "API cost", statRuntime: (m) => `local runtime, model ${m}`, statTokens: "tokens in total",
    count: (a, b) => `${a} of ${b} products`, noResults: "results.json not found. Run make check-all first.",
    artNo: "Item no.", ean: "EAN", noFindings: "No findings.", rule: "Legal basis", suggestion: "Suggested fix",
    apply: "Apply fix", applied: "Applied", reset: "Reset", was: (s) => `before ${s}`,
    resetHint: "Changes live in the browser only.", modelError: "Model error: ",
    llmRun: "AI run", model: "Model", runtime: "Runtime", tokens: "Tokens (prompt / answer)", apiCost: "API cost",
    cache: "From cache", yes: "yes", no: "no", cacheShort: "cache", nutrients: "Nutrition per 100 g", missing: "missing",
    productText: "Product text (German)", ingredients: "Ingredients", offLink: "Entry at Open Food Facts",
    fieldName: "Name", fieldGeneric: "Designation", fieldLabels: "Labels", fieldDescription: "Description",
    n_energy: "Energy (kcal)", n_fat: "Fat", n_sat: "of which saturated", n_carbs: "Carbohydrates",
    n_sugars: "of which sugars", n_protein: "Protein", n_salt: "Salt",
    locale: "en-GB",
  },
};
const CHECKS = ["luecken", "widersprueche", "allergene", "claims"];
const STATUSES = ["red", "yellow", "green"];
const NUTRIENTS = {"energy-kcal_100g": "n_energy", fat_100g: "n_fat", "saturated-fat_100g": "n_sat",
  carbohydrates_100g: "n_carbs", sugars_100g: "n_sugars", proteins_100g: "n_protein", salt_100g: "n_salt"};
const FIELDS = {name: "fieldName", generic_name: "fieldGeneric", labels: "fieldLabels", description: "fieldDescription"};
const state = {source: "brand", status: "all", check: "all", q: "", data: null, lang: "de", applied: {}, open: null};

function store(key, value) {  // localStorage kann fehlen oder werfen (privates Fenster), dann einfach ohne
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch (e) { /* ignorieren */ }
  return null;
}
const t = (k, ...a) => { const v = I18N[state.lang][k]; return typeof v === "function" ? v(...a) : v; };
const pick = (f, k) => (state.lang === "en" && f[k + "_en"]) || f[k] || "";

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
const fmt = (n) => new Intl.NumberFormat(t("locale")).format(n);
const dot = (s) => el("span", {class: "dot " + s, title: t(s)});

// Ergebnis eines Produkts unter Beruecksichtigung uebernommener Korrekturen
const appliedOf = (r) => state.applied[r.code] || [];
const eff = (r) => Fix.effective(r, appliedOf(r));
function saveApplied() { store("labellab.applied", JSON.stringify({gen: state.data.meta.generated, map: state.applied})); }

function setLang(lang) {
  state.lang = lang;
  store("labellab.lang", lang);
  document.documentElement.lang = lang;
  renderAll();
}

function renderStatic() {
  document.querySelectorAll("[data-i18n]").forEach((n) => { n.textContent = t(n.dataset.i18n); });
  document.querySelectorAll("[data-i18n-html]").forEach((n) => { n.innerHTML = t(n.dataset.i18nHtml); });
  document.querySelectorAll("[data-i18n-ph]").forEach((n) => { n.placeholder = t(n.dataset.i18nPh); });
  document.querySelectorAll("[data-i18n-aria]").forEach((n) => { n.setAttribute("aria-label", t(n.dataset.i18nAria)); });
  $("lang").replaceChildren(...["de", "en"].map((l) => el("button", {"aria-pressed": String(state.lang === l),
    text: l.toUpperCase(), onclick: () => setLang(l)})));
}

function sourceChips() {
  const box = $("sourceFilter");
  box.replaceChildren();
  for (const [value, key] of [["brand", "brandSource"], ["off", "offSource"]]) {
    const n = state.data.results.filter((r) => r.source === value).length;
    box.append(el("button", {class: "chip", "aria-pressed": String(state.source === value), text: `${t(key)} (${n})`,
      onclick: () => { state.source = value; sourceChips(); renderStats(); render(); }}));
  }
}

function chips(box, items, key) {
  box.replaceChildren();
  for (const [value, label] of items) {
    box.append(el("button", {class: "chip", "aria-pressed": String(state[key] === value), text: label,
      onclick: () => { state[key] = value; chips(box, items, key); render(); }}));
  }
}
function filterChips() {
  chips($("statusFilter"), [["all", t("all")], ...STATUSES.map((s) => [s, t(s)])], "status");
  chips($("checkFilter"), [["all", t("allChecks")], ...CHECKS.map((c) => [c, t(c)])], "check");
}

function sourceRows() { return state.data.results.filter((r) => r.source === state.source); }

function renderStats() {
  const meta = state.data.meta, rows = sourceRows();
  const c = {red: 0, yellow: 0, green: 0};
  rows.forEach((r) => { c[eff(r).status] += 1; });
  $("claim").replaceChildren(t("checked", fmt(meta.products)), el("b", {text: t("cost")}), t("localMin", fmt(meta.llm_minutes)));
  const items = [
    [fmt(rows.length), t("statProducts")], [fmt(c.red), t("statRed")], [fmt(c.yellow), t("statYellow")],
    [fmt(c.green), t("statGreen")], ["0 €", t("statCost")], [fmt(meta.llm_minutes) + " Min.", t("statRuntime", meta.model)],
    [fmt(meta.tokens_in + meta.tokens_out), t("statTokens")],
  ];
  $("stats").replaceChildren(...items.map(([n, l]) =>
    el("div", {class: "stat"}, el("div", {class: "n", text: n}), el("div", {class: "l", text: l}))));
}

function visible() {
  const q = state.q.trim().toLowerCase();
  return sourceRows().filter((r) => {
    const e = eff(r);
    return (state.status === "all" || e.status === state.status) &&
      (state.check === "all" || e.checks[state.check] !== "green") &&
      (!q || (r.name + " " + r.brand).toLowerCase().includes(q));
  });
}

function render() {
  const rows = visible();
  $("count").textContent = t("count", rows.length, sourceRows().length);
  $("list").replaceChildren(...rows.map((r) => {
    const e = eff(r);
    return el("li", {class: "row", tabindex: "0", role: "button", onclick: () => openDetail(r),
      onkeydown: (ev) => { if (ev.key === "Enter") openDetail(r); }},
      dot(e.status),
      el("div", {}, el("div", {class: "name", text: r.name}), el("div", {class: "brand", text: r.brand || t("noBrand")})),
      el("div", {class: "mini"}, ...CHECKS.map((k) => dot(e.checks[k]))),
      el("div", {class: "time", text: r.llm.cached ? t("cacheShort") : r.llm.seconds + " s"}));
  }));
}

function renderAll() {
  renderStatic();
  if (!state.data) return;
  $("placeholder").hidden = !state.data.meta.placeholder;
  renderStats(); sourceChips(); filterChips(); render();
  if (state.open && !$("detail").hidden) openDetail(state.open, true);
}

function applyFix(r, idx) {
  state.applied[r.code] = [...appliedOf(r), idx];
  saveApplied(); renderStats(); render(); openDetail(r, true, true);
}
function resetFix(r) {
  delete state.applied[r.code];
  saveApplied(); renderStats(); render(); openDetail(r, true, true);
}

// Produkttext als Diff: alt rot durchgestrichen, neu in Gold
function diffNodes(segs, sep) {
  const out = [];
  segs.forEach((s, i) => {
    if (i && sep) out.push(sep);
    if (s.text !== undefined) out.push(s.text);
    else { out.push(el("del", {text: s.del})); if (s.ins) out.push(" ", el("ins", {text: s.ins})); }
  });
  return out;
}

function openDetail(r, keepScroll = false, flash = false) {
  state.open = r;
  const body = $("detailBody"), e = eff(r), applied = appliedOf(r);
  const scroll = $("detail").scrollTop;
  body.replaceChildren(el("h2", {text: r.name}),
    el("p", {class: "muted", text: `${r.brand || t("noBrand")} · ${r.source === "brand" ? t("artNo") : t("ean")} ${r.code}`}));
  const light = el("div", {class: "light " + e.status + (flash ? " flash" : "")}, dot(e.status), el("b", {text: t(e.status)}));
  if (e.status !== r.status) light.append(el("span", {class: "was", text: t("was", t(r.status))}));
  body.append(light);
  if (applied.length) body.append(el("p", {class: "muted"}, `${t("resetHint")} `,
    el("button", {class: "reset", text: t("reset"), onclick: () => resetFix(r)})));

  for (const key of CHECKS) {
    body.append(el("h3", {text: t(key)}));
    const items = r.findings.map((f, i) => [f, i]).filter(([f]) => f.check === key);
    if (!items.length) { body.append(el("p", {class: "muted", text: t("noFindings")})); continue; }
    for (const [f, i] of items) {
      const done = applied.includes(i);
      const box = el("div", {class: "finding " + (f.severity === "error" ? "red" : "yellow") + (done ? " done" : "")},
        el("div", {text: pick(f, "message")}));
      if (f.rule) box.append(el("div", {class: "rule"}, el("b", {text: t("rule") + ": "}), pick(f, "rule")));
      if (f.suggestion) {
        box.append(el("div", {class: "fix"}, el("span", {text: t("suggestion")}), el("div", {text: pick(f, "suggestion")})));
        if (done) box.append(el("div", {class: "tag", text: t("applied")}));
        else if (Fix.canApply(f, r.product, r.name)) {
          box.append(el("button", {class: "apply", text: t("apply"), onclick: () => applyFix(r, i)}));
        }
      }
      body.append(box);
    }
  }
  if (r.llm.error) body.append(el("p", {class: "muted", text: t("modelError") + r.llm.error}));

  const claimsApplied = applied.map((i) => r.findings[i]).filter((f) => f.check === "claims");
  const d = Fix.diff(r.product, r.name, claimsApplied);
  const changed = Object.keys(d).filter((k) => d[k].some((s) => s.text === undefined));
  body.append(el("h3", {text: t("productText")}));
  for (const k of changed) {
    if (k === "description") continue;
    body.append(el("div", {class: "field", text: t(FIELDS[k])}), el("p", {class: "text"}, ...diffNodes(d[k])));
  }
  if (d.description.length) body.append(el("p", {class: "text"}, ...diffNodes(d.description, " ")));

  body.append(el("h3", {text: t("llmRun")}), table([
    [t("model"), `${r.llm.model} (${r.llm.mode})`], [t("runtime"), r.llm.seconds + " s"],
    [t("tokens"), `${fmt(r.llm.tokens_in)} / ${fmt(r.llm.tokens_out)}`],
    [t("apiCost"), "0 €"], [t("cache"), r.llm.cached ? t("yes") : t("no")]]));
  const n = r.product.nutriments || {};
  body.append(el("h3", {text: t("nutrients")}), table(Object.entries(NUTRIENTS).map(
    ([k, l]) => [t(l), n[k] === undefined ? t("missing") : String(n[k])])));
  body.append(el("h3", {text: t("ingredients")}), el("p", {text: r.product.ingredients || t("missing")}));
  if (r.source === "off" && r.product.url) body.append(el("p", {}, el("a", {href: r.product.url, text: t("offLink")})));
  $("detail").hidden = false;
  $("detail").scrollTop = keepScroll ? scroll : 0;
}
const table = (rows) => el("table", {}, ...rows.map(([a, b]) => el("tr", {}, el("td", {text: a}), el("td", {text: b}))));

$("close").onclick = () => { $("detail").hidden = true; };
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("detail").hidden = true; });
$("search").oninput = (e) => { state.q = e.target.value; render(); };

const savedLang = store("labellab.lang");
if (savedLang === "de" || savedLang === "en") state.lang = savedLang;
document.documentElement.lang = state.lang;
renderStatic();

fetch("public/results.json").then((r) => r.json()).then((data) => {
  state.data = data;
  try {  // gemerkte Korrekturen nur, wenn sie zu diesem results.json gehoeren (Indizes sonst falsch)
    const saved = JSON.parse(store("labellab.applied") || "null");
    state.applied = saved && saved.gen === data.meta.generated ? saved.map : {};
  } catch (e) { state.applied = {}; }
  renderAll();
}).catch(() => { $("count").textContent = t("noResults"); });
