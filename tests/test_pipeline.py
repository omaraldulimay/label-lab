import json

from labellab.llm import FakeLLM
from labellab.pipeline import ampel, export_results, load_snapshot, run_all


def test_ampel():
    assert ampel([]) == "green"
    assert ampel([{"severity": "warn"}]) == "yellow"
    assert ampel([{"severity": "warn"}, {"severity": "error"}]) == "red"


def test_snapshot_has_about_200_products():
    snap = load_snapshot()
    assert 150 <= len(snap["products"]) <= 250 and "ODbL" in snap["source"]


def test_run_and_export(tmp_path):
    products = load_snapshot()["products"][:20]
    llm = FakeLLM()
    results = run_all(products, llm)
    meta = export_results(results, llm, tmp_path / "r.json")
    data = json.loads((tmp_path / "r.json").read_text())
    assert meta["placeholder"] is True and meta["api_cost_eur"] == 0 and meta["products"] == 20
    assert sum(meta["counts"].values()) == 20 and len(data["results"]) == 20
    assert data["results"][0]["status"] == "red" or meta["counts"]["red"] == 0  # rote zuerst
