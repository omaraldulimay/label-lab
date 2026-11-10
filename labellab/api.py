"""FastAPI Dienst: Produkte laden, pruefen, Ergebnisse exportieren."""
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from . import store
from .llm import LLMError, get_llm
from .pipeline import (ROOT, check_product, default_cache, export_results, load_snapshot, run_all,
                       summarize)

log = logging.getLogger("labellab")
app = FastAPI(title="Label Lab")
LAST_ALERT: dict = {}


@app.get("/health")
def health():
    llm = get_llm()
    return {"ok": True, "mode": llm.mode, "model": llm.model}


@app.post("/load")
def load():
    """Snapshot (Open Food Facts, ODbL) in die Datenbank laden."""
    store.init_db()
    return {"loaded": store.save_products(load_snapshot()["products"])}


@app.post("/check/{code}")
def check_one(code: str):
    p = store.get_product(code)
    if not p:
        raise HTTPException(404, "Produkt nicht gefunden")
    llm = get_llm()
    result = check_product(p, llm, default_cache(llm))
    store.save_result(result)
    return result


@app.post("/check-all")
def check_all():
    llm = get_llm()
    try:
        results = run_all(store.all_products(), llm, default_cache(llm))
    except LLMError as exc:
        raise HTTPException(503, str(exc))
    for r in results:
        store.save_result(r)
    red = [{"code": r["code"], "name": r["name"], "brand": r["brand"]} for r in results if r["status"] == "red"]
    return {"summary": summarize(results, llm), "red_count": len(red), "red": red}


@app.get("/results")
def results():
    return store.all_results()


@app.post("/export")
def export():
    return export_results(store.all_results(), get_llm())


@app.post("/alert")
def alert(payload: dict):
    """Ziel fuer den n8n Alarm: schreibt ins Log und merkt sich den letzten Alarm."""
    LAST_ALERT.clear()
    LAST_ALERT.update(payload)
    log.warning("ALARM: %s rote Produkte", payload.get("red_count"))
    return {"received": True}


@app.get("/alert")
def last_alert():
    return LAST_ALERT


web = Path(ROOT) / "web"
if web.exists():  # Dashboard unter http://localhost:8000/
    app.mount("/", StaticFiles(directory=web, html=True), name="web")
