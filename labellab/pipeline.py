"""Alle Pruefungen eines Produkts zusammenfuehren und Ergebnisse exportieren."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from . import rules
from .allergens import check_allergens
from .llm import BUDGET_USD, ResultCache, check_claims, get_llm

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "data" / "products.json"
BRAND_CATALOG = ROOT / "data" / "brand_catalog.json"
RESULTS_JSON = ROOT / "web" / "public" / "results.json"
CACHE_FILE = ROOT / "data" / "llm_cache.json"
CHECKS = ["luecken", "widersprueche", "allergene", "claims"]
ORDER = {"green": 0, "yellow": 1, "red": 2}


def load_snapshot(path: Path = SNAPSHOT) -> dict:
    return json.loads(Path(path).read_text())


def load_brand_catalog(path: Path = BRAND_CATALOG) -> dict:
    return json.loads(Path(path).read_text())


def load_products() -> list[dict]:
    """Markenkatalog zuerst, danach Open Food Facts. Jedes Produkt bekommt seine Quelle."""
    brand = [dict(p, source="brand") for p in load_brand_catalog()["products"]]
    off = [dict(p, source="off") for p in load_snapshot()["products"]]
    return brand + off


def ampel(findings: list[dict]) -> str:
    if any(f["severity"] == "error" for f in findings):
        return "red"
    return "yellow" if findings else "green"


def cap_warn(findings: list[dict]) -> list[dict]:
    """Open Food Facts: Funde sind Luecken im Datenbankeintrag, hoechstens gelb."""
    return [dict(f, severity="warn") for f in findings]


def claim_findings(res) -> list[dict]:
    out = []
    for f in res.findings:
        out.append({"check": "claims", "code": "claim_" + f["verdict"],
                    "severity": "error" if f["verdict"] == "unzulaessig" else "warn",
                    "message": f"\"{f['claim']}\": {f['reason']}",
                    "message_en": f"\"{f['claim']}\": {f['reason_en']}",
                    "claim": f["claim"], "reason": f["reason"], "reason_en": f["reason_en"],
                    "rule": f["rule"], "rule_en": f["rule_en"],
                    "suggestion": f["suggestion"], "suggestion_en": f["suggestion_en"]})
    return out


def check_product(p: dict, llm, cache: ResultCache | None = None) -> dict:
    res = check_claims(p, llm, cache)
    off = p.get("source", "off") != "brand"
    per_check = {
        "luecken": rules.check_gaps(p, off),
        "widersprueche": rules.check_contradictions(p, off),
        "allergene": check_allergens(p.get("ingredients", ""), p.get("allergens_tags", []), off),
        "claims": claim_findings(res),
    }
    if off:
        per_check = {c: cap_warn(fs) for c, fs in per_check.items()}
    findings = [f for c in CHECKS for f in per_check[c]]
    return {
        "code": p["code"], "name": p["name"], "brand": p.get("brand", ""), "source": p.get("source", "off"),
        "status": ampel(findings),
        "checks": {c: ampel(per_check[c]) for c in CHECKS},
        "findings": findings,
        "llm": {"model": res.model, "mode": res.mode, "cached": res.cached, "seconds": res.seconds,
                "tokens_in": res.tokens_in, "tokens_out": res.tokens_out, "error": res.error,
                "cost_usd": round(res.cost_usd, 6), "allowed": res.allowed, "suspicious": res.suspicious},
        "product": {k: p.get(k) for k in ("generic_name", "labels", "description", "ingredients", "allergens_tags",
                                           "serving_size", "nutriments", "url")},
    }


def _counts(rs: list[dict]) -> dict:
    return {s: sum(1 for r in rs if r["status"] == s) for s in ORDER}


def rescore(data: dict) -> dict:
    """Regeln und Ampel aus vorhandenen Ergebnissen neu berechnen, ohne Modellaufruf.

    Die Claim Funde und der KI Teil (llm, meta Kosten) bleiben unveraendert.
    """
    results = []
    for r in data["results"]:
        p = dict(r["product"], code=r["code"], name=r["name"], brand=r["brand"], source=r["source"])
        off = r["source"] != "brand"
        per_check = {
            "luecken": rules.check_gaps(p, off),
            "widersprueche": rules.check_contradictions(p, off),
            "allergene": check_allergens(p.get("ingredients", ""), p.get("allergens_tags", []), off),
            "claims": [f for f in r["findings"] if f["check"] == "claims"],
        }
        if off:
            per_check = {c: cap_warn(fs) for c, fs in per_check.items()}
        findings = [f for c in CHECKS for f in per_check[c]]
        results.append(dict(r, status=ampel(findings), checks={c: ampel(per_check[c]) for c in CHECKS},
                            findings=findings))
    results.sort(key=lambda r: (-ORDER[r["status"]], r["name"].lower()))
    meta = dict(data["meta"], counts=_counts(results), rescored_from=data["meta"]["generated"],
                generated=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    meta["sources"] = {s: {"products": sum(1 for r in results if r["source"] == s),
                           "counts": _counts([r for r in results if r["source"] == s])} for s in ("brand", "off")}
    return {"meta": meta, "results": results}


def summarize(results: list[dict], llm) -> dict:
    counts = {s: sum(1 for r in results if r["status"] == s) for s in ORDER}
    seconds = sum(r["llm"]["seconds"] for r in results)
    cost = sum(r["llm"]["cost_usd"] for r in results)
    sources = {}
    for s in ("brand", "off"):
        rs = [r for r in results if r.get("source") == s]
        sources[s] = {"products": len(rs), "counts": {k: sum(1 for r in rs if r["status"] == k) for k in ORDER}}
    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "Markenkatalog und Open Food Facts (ODbL), https://world.openfoodfacts.org",
        "sources": sources,
        "mode": llm.mode, "model": llm.model,
        "placeholder": llm.mode == "fake",
        "products": len(results), "counts": counts,
        "api_cost_usd": round(cost, 4),
        "budget_usd": BUDGET_USD if llm.mode == "claude" else 0,
        "claims_allowed": sum(r["llm"]["allowed"] for r in results),
        "claims_to_model": sum(r["llm"]["suspicious"] for r in results),
        "tokens_in": sum(r["llm"]["tokens_in"] for r in results),
        "tokens_out": sum(r["llm"]["tokens_out"] for r in results),
        "llm_seconds": round(seconds, 1), "llm_minutes": round(seconds / 60, 1),
        "cached": sum(1 for r in results if r["llm"]["cached"]),
        "llm_errors": sum(1 for r in results if r["llm"]["error"]),
    }


def run_all(products: list[dict], llm=None, cache: ResultCache | None = None, progress=None) -> list[dict]:
    llm = llm or get_llm()
    if hasattr(llm, "ping"):
        llm.ping()  # bricht frueh und mit klarer Meldung ab, wenn Ollama fehlt
    results = []
    for i, p in enumerate(products, 1):
        results.append(check_product(p, llm, cache))
        if progress:
            progress(i, len(products), results[-1])
    return results


def export_results(results: list[dict], llm, path: Path = RESULTS_JSON) -> dict:
    meta = summarize(results, llm)
    results = sorted(results, key=lambda r: (-ORDER[r["status"]], r["name"].lower()))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps({"meta": meta, "results": results}, ensure_ascii=False, indent=1))
    return meta


def default_cache(llm=None) -> ResultCache:
    """Platten-Cache fuer echte Laeufe. Der Fake rechnet nichts und bekommt nur einen Speicher Cache."""
    if llm is not None and llm.mode == "fake":
        return ResultCache(None)
    return ResultCache(os.environ.get("LLM_CACHE", CACHE_FILE))
