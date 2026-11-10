import json

from labellab.llm import FakeLLM
from labellab.pipeline import (ampel, export_results, load_brand_catalog, load_products, load_snapshot,
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
    assert meta["placeholder"] is True and meta["api_cost_eur"] == 0 and meta["products"] == 20
    assert sum(meta["counts"].values()) == 20 and len(data["results"]) == 20
    assert data["results"][0]["status"] == "red" or meta["counts"]["red"] == 0  # rote zuerst


def test_brand_catalog_shape():
    cat = load_brand_catalog()["products"]
    assert 45 <= len(cat) <= 60
    assert len({p["code"] for p in cat}) == len(cat)
    for p in cat:
        assert p["brand"] == "Stahlkern" and p["description"] and p["serving_size"] is not None
        assert 3 <= p["description"].count(". ") + 1 <= 7


def test_brand_catalog_mix_of_clean_and_problems():
    results = run_all([dict(p, source="brand") for p in load_brand_catalog()["products"]], FakeLLM())
    red = sum(1 for r in results if r["status"] == "red")
    green = sum(1 for r in results if r["status"] == "green")
    assert green >= 0.5 * len(results) and 0.2 * len(results) <= red <= 0.45 * len(results)
    by_code = {r["code"]: r for r in results}
    assert by_code["SK-1014"]["checks"]["widersprueche"] == "red"   # Kalorien passen nicht zu den Makros
    assert by_code["SK-1042"]["checks"]["allergene"] == "red"       # Soja nicht deklariert
    assert by_code["SK-1093"]["checks"]["claims"] == "red"          # Fatburner


def test_sources_are_tagged_and_summarized(tmp_path):
    products = load_products()
    assert {p["source"] for p in products} == {"brand", "off"}
    llm = FakeLLM()
    export_results(run_all(products[:5] + products[-5:], llm), llm, tmp_path / "r.json")
    meta = json.loads((tmp_path / "r.json").read_text())["meta"]
    assert meta["sources"]["brand"]["products"] == 5 and meta["sources"]["off"]["products"] == 5
