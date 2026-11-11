import json

from labellab.llm import FakeLLM
from labellab.pipeline import (ampel, check_product, export_results, load_brand_catalog, load_products, load_snapshot,
                               run_all)


def test_ampel():
    assert ampel([]) == "green"
    assert ampel([{"severity": "warn"}]) == "yellow"
    assert ampel([{"severity": "warn"}, {"severity": "error"}]) == "red"


def test_snapshot_has_about_200_products():
    snap = load_snapshot()
    assert 150 <= len(snap["products"]) <= 250 and "ODbL" in snap["source"]
    names = " ".join(p["name"].lower() for p in snap["products"])
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
