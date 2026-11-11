import json

from labellab.llm import FakeLLM
from labellab.pipeline import (ampel, check_product, export_results, load_brand_catalog, load_products, load_snapshot,
                               run_all)


def test_ampel():
    assert ampel([]) == "green"
    assert ampel([{"severity": "warn"}]) == "yellow"
    assert ampel([{"severity": "warn"}, {"severity": "error"}]) == "red"


def test_snapshot_is_large_unique_and_multi_country():
    snap = load_snapshot()
    prods = snap["products"]
    assert 1500 <= len(prods) <= 2100 and "ODbL" in snap["source"]
    assert len({p["code"] for p in prods}) == len(prods)  # keine Duplikate
    assert len({p["country"] for p in prods if p.get("country")}) >= 8
    assert {"protein", "riegel", "creatin", "amino", "vitamine", "omega", "pre"} <= {p["category"] for p in prods}
    names = " ".join(p["name"].lower() for p in prods)
    for food in ("linsen", "baked beans", "nudeln"):
        assert food not in names


def test_run_and_export(tmp_path):
    products = load_products()[:10] + load_products()[-10:]
    llm = FakeLLM()
    results = run_all(products, llm)
    meta = export_results(results, llm, tmp_path / "r.json")
    data = json.loads((tmp_path / "r.json").read_text())
    assert meta["placeholder"] is True and meta["api_cost_usd"] == 0 and meta["products"] == 20
    assert sum(meta["counts"].values()) == 20 and len(data["results"]) == 20
    assert data["results"][0]["status"] == "red" or meta["counts"]["red"] == 0  # rote zuerst


def test_brand_catalog_shape():
    cat = load_brand_catalog()["products"]
    assert 45 <= len(cat) <= 60
    assert len({p["code"] for p in cat}) == len(cat)
    for p in cat:
        assert p["brand"] == "RAWFORM" and p["description"] and p["serving_size"] is not None
        assert 3 <= p["description"].count(". ") + 1 <= 7


def test_brand_catalog_mix_of_clean_and_problems():
    results = run_all([dict(p, source="brand") for p in load_brand_catalog()["products"]], FakeLLM())
    red = sum(1 for r in results if r["status"] == "red")
    green = sum(1 for r in results if r["status"] == "green")
    assert green >= 0.5 * len(results) and 0.2 * len(results) <= red <= 0.45 * len(results)
    by_code = {r["code"]: r for r in results}
    assert by_code["RF-1014"]["checks"]["widersprueche"] == "red"   # Kalorien passen nicht zu den Makros
    assert by_code["RF-1042"]["checks"]["allergene"] == "red"       # Soja nicht deklariert
    assert by_code["RF-1093"]["checks"]["claims"] == "red"          # Fatburner


def test_sources_are_tagged_and_summarized(tmp_path):
    products = load_products()
    assert {p["source"] for p in products} == {"brand", "off"}
    llm = FakeLLM()
    export_results(run_all(products[:5] + products[-5:], llm), llm, tmp_path / "r.json")
    meta = json.loads((tmp_path / "r.json").read_text())["meta"]
    assert meta["sources"]["brand"]["products"] == 5 and meta["sources"]["off"]["products"] == 5


def _off_product():
    return {"code": "1", "name": "x", "brand": "ESN", "source": "off", "ingredients": "", "serving_size": "",
            "allergens_tags": [], "nutriments": {}}


def test_off_findings_are_at_most_warn_and_neutral():
    from labellab.llm import FakeLLM as F
    r = check_product(_off_product(), F())
    assert r["status"] == "yellow" and all(f["severity"] == "warn" for f in r["findings"])
    msgs = {f["code"]: f for f in r["findings"]}
    assert msgs["zutaten_fehlen"]["message"] == "Im Datenbankeintrag fehlt die Zutatenliste."
    assert msgs["zutaten_fehlen"]["message_en"] == "The database entry has no ingredient list."
    brand = check_product(dict(_off_product(), source="brand"), F())
    assert brand["status"] == "red"


def test_off_allergen_and_contradiction_are_warn():
    from labellab.llm import FakeLLM as F
    p = dict(_off_product(), ingredients="Sojalecithin", serving_size="30 g",
             nutriments={"energy-kcal_100g": 900, "fat_100g": 1, "carbohydrates_100g": 1, "sugars_100g": 5,
                         "proteins_100g": 1, "salt_100g": 0.1})
    r = check_product(p, F())
    assert {"allergene", "widersprueche"} <= {f["check"] for f in r["findings"]}
    assert r["status"] == "yellow" and "Datenbankeintrag" in r["findings"][0]["message"]


def test_rescore_keeps_claims_and_cost_without_model(tmp_path):
    from labellab.pipeline import rescore
    llm = FakeLLM()
    prods = [dict(_off_product(), description="Das verbrennt Fett."), dict(load_products()[0])]
    results = run_all(prods, llm)
    export_results(results, llm, tmp_path / "r.json")
    data = json.loads((tmp_path / "r.json").read_text())
    out = rescore(data)
    assert out["meta"]["api_cost_usd"] == data["meta"]["api_cost_usd"]
    assert out["meta"]["sources"]["off"]["counts"]["red"] == 0
    old = {r["code"]: r for r in data["results"]}
    for r in out["results"]:
        assert r["llm"] == old[r["code"]]["llm"]
        assert [f for f in r["findings"] if f["check"] == "claims"] == \
            [dict(f, severity="warn") if r["source"] == "off" else f
             for f in old[r["code"]]["findings"] if f["check"] == "claims"]


def test_compact_roundtrip_and_size(tmp_path):
    from labellab.pipeline import read_results, write_results
    llm = FakeLLM()
    prods = load_products()[:30] + [dict(_off_product(), code="9", description="Das verbrennt Fett.")]
    results = run_all(prods, llm)
    meta = export_results(results, llm, tmp_path / "r.json")
    raw = json.loads((tmp_path / "r.json").read_text())
    assert raw["meta"]["rules"] and '"rule":' not in json.dumps(raw["results"], separators=(",", ":"))
    data = read_results(tmp_path / "r.json")
    by = {r["code"]: r for r in data["results"]}
    for r in results:
        out = by[r["code"]]
        assert out["status"] == r["status"] and out["checks"] == r["checks"]
        assert out["findings"] == r["findings"] and out["llm"] == r["llm"]
    write_results(data, tmp_path / "r2.json")  # nochmal schreiben aendert nichts
    assert json.loads((tmp_path / "r2.json").read_text())["results"] == raw["results"]
    assert meta["products"] == len(prods)


def test_estimate_counts_model_load_without_calling_a_model(tmp_path):
    from labellab.llm import ResultCache
    from labellab.pipeline import estimate_model_load
    prods = [dict(_off_product(), code=str(i), description="Das verbrennt Fett. Heilt Erkältungen.")
             for i in range(3)] + [dict(_off_product(), code="x", description="Neutral.")]
    est = estimate_model_load(prods, ResultCache(None))
    assert est["model_calls"] == 3 and est["sentences"] == 6 and est["cached_calls"] == 0
    assert 0 < est["est_cost_usd"] < 0.01
    assert estimate_model_load(prods[3:], ResultCache(None))["model_calls"] == 0


def test_real_cache_hits_are_counted_in_the_estimate(tmp_path):
    from labellab.llm import DEFAULT_CLAUDE_MODEL, ResultCache, cache_key, prefilter
    from labellab.pipeline import estimate_model_load
    p = dict(_off_product(), description="Das verbrennt Fett.")
    cache = ResultCache(tmp_path / "c.json")
    cache.set(cache_key(DEFAULT_CLAUDE_MODEL, "\n".join(prefilter(p).suspicious)), {"verdicts": []})
    est = estimate_model_load([p], cache)
    assert est["cached_calls"] == 1 and est["model_calls"] == 0 and est["est_cost_usd"] == 0


def test_full_snapshot_rules_and_export_are_fast(tmp_path):
    import time
    products = load_products()
    assert len(products) >= 1500
    llm = FakeLLM()
    start = time.monotonic()
    results = run_all(products, llm)
    export_results(results, llm, tmp_path / "r.json")
    assert time.monotonic() - start < 10
    assert (tmp_path / "r.json").stat().st_size < 3_000_000


def test_shipped_estimate_stays_under_budget_with_real_cache():
    from labellab.pipeline import default_cache, estimate_model_load
    est = estimate_model_load(load_products(), default_cache())
    assert est["est_cost_usd"] <= 0.25
