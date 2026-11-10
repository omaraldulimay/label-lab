from fastapi.testclient import TestClient

from labellab import api
from labellab.pipeline import load_snapshot


def memory_store(monkeypatch, tmp_path):
    products, results = {}, {}
    monkeypatch.setattr(api.store, "init_db", lambda: None)
    monkeypatch.setattr(api.store, "save_products", lambda ps: products.update({p["code"]: p for p in ps}) or len(ps))
    monkeypatch.setattr(api.store, "get_product", lambda c: products.get(c))
    monkeypatch.setattr(api.store, "all_products", lambda: list(products.values()))
    monkeypatch.setattr(api.store, "save_result", lambda r: results.update({r["code"]: r}))
    monkeypatch.setattr(api.store, "all_results", lambda: list(results.values()))
    monkeypatch.setenv("LLM_CACHE", str(tmp_path / "cache.json"))


def test_load_check_and_alert(monkeypatch, tmp_path):
    memory_store(monkeypatch, tmp_path)
    monkeypatch.setattr(api, "load_snapshot", lambda: {"products": load_snapshot()["products"][:15]})
    c = TestClient(api.app)
    assert c.get("/health").json()["mode"] == "fake"
    assert c.post("/load").json()["loaded"] == 15
    code = api.store.all_products()[0]["code"]
    assert c.post(f"/check/{code}").json()["code"] == code
    assert c.post("/check/doesnotexist").status_code == 404
    out = c.post("/check-all").json()
    assert out["summary"]["products"] == 15 and out["red_count"] == len(out["red"])
    assert c.post("/alert", json={"red_count": 3}).json()["received"]
    assert c.get("/alert").json()["red_count"] == 3
