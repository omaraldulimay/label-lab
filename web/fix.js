// Reine Logik fuer "Korrektur uebernehmen": Passage ersetzen und Ampel neu berechnen.
// Ohne DOM, damit sie auch unter Node getestet werden kann.
(function (root) {
  const SENTENCE = /(?<=[.!?])\s+/;
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

  // Ampel wie in Python: rot bei einem Fehler, gelb bei Hinweisen, sonst gruen.
  function ampel(findings) {
    if (findings.some((f) => f.severity === "error")) return "red";
    return findings.length ? "yellow" : "green";
  }

  function claimRe(claim) { return new RegExp(esc(claim), "i"); }

  // Laesst sich die beanstandete Passage im Produkttext finden?
  function canApply(f, product, name) {
    if (f.check !== "claims" || !f.suggestion || !f.claim) return false;
    const re = claimRe(f.claim);
    return [name, product.generic_name, product.labels, product.description].some((t) => t && re.test(t));
  }

  // Segmente je Feld: {text} bleibt, {del, ins} wurde ersetzt. Beschreibung satzweise, kurze Felder wortweise.
  function diff(product, name, applied) {
    const fields = {name: name || "", generic_name: product.generic_name || "", labels: product.labels || "",
      description: product.description || ""};
    const out = {};
    for (const [key, text] of Object.entries(fields)) {
      out[key] = key === "description" ? text.split(SENTENCE).filter(Boolean).map((s) => ({text: s})) : [{text}];
    }
    for (const f of applied) {
      const re = claimRe(f.claim);
      let placed = false;
      for (const [key, segs] of Object.entries(out)) {
        const next = [];
        for (const seg of segs) {
          if (seg.text === undefined || !re.test(seg.text)) { next.push(seg); continue; }
          if (key === "description") {
            next.push({del: seg.text, ins: placed ? "" : f.suggestion});
            placed = true;
          } else {  // kurzes Feld: nur das Wort entfernen
            let rest = seg.text;
            for (let m = re.exec(rest); m; m = re.exec(rest)) {
              if (m.index > 0) next.push({text: rest.slice(0, m.index)});
              next.push({del: m[0], ins: ""});
              rest = rest.slice(m.index + m[0].length);
            }
            if (rest) next.push({text: rest});
          }
        }
        out[key] = next;
      }
    }
    return out;
  }

  // Text eines Felds nach den Aenderungen. Die Beschreibung wird mit Leerzeichen zwischen den Saetzen gebaut.
  function joinSegs(segs, sep) {
    const parts = segs.map((s) => (s.text !== undefined ? s.text : s.ins)).filter(Boolean);
    return parts.join(sep || "").replace(/\s{2,}/g, " ").trim();
  }

  // Ergebnis nach dem Uebernehmen: offene Funde, Ampel gesamt und je Pruefung.
  function effective(r, appliedIdx) {
    const open = r.findings.filter((f, i) => !appliedIdx.includes(i));
    const checks = {};
    for (const c of Object.keys(r.checks)) checks[c] = ampel(open.filter((f) => f.check === c));
    return {status: ampel(open), checks, open};
  }

  const api = {ampel, canApply, diff, joinSegs, effective};
  if (typeof module !== "undefined") module.exports = api; else root.Fix = api;
})(typeof window !== "undefined" ? window : globalThis);
