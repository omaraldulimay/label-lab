"""Ohne Datenbank und Docker: Snapshot pruefen und results.json schreiben.

  python -m labellab.cli            # Modus aus LLM_MODE (Standard fake)
  python -m labellab.cli --rescore  # Ampel in results.json neu berechnen, ohne Modellaufruf
"""
import json
import sys
import time

from .llm import LLMError, get_llm
from .pipeline import RESULTS_JSON, default_cache, export_results, load_products, rescore, run_all


def main() -> int:
    if "--rescore" in sys.argv:
        data = rescore(json.loads(RESULTS_JSON.read_text()))
        RESULTS_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=1))
        print(data["meta"]["sources"])
        return 0
    try:
        llm = get_llm()
    except LLMError as exc:
        print("Abbruch:", exc, file=sys.stderr)
        return 1
    products = load_products()
    start = time.monotonic()

    def progress(i, n, r):
        print(f"[{i}/{n}] {r['status']:6} {r['name'][:50]}  ({r['llm']['seconds']} s, {r['llm']['cost_usd']:.5f} USD)", flush=True)

    try:
        results = run_all(products, llm, default_cache(llm), progress)
    except LLMError as exc:
        print("Abbruch:", exc, file=sys.stderr)
        return 1
    meta = export_results(results, llm)
    print(f"{meta['products']} Produkte, {meta['counts']}, Modell {meta['model']} ({meta['mode']}), "
          f"{meta['llm_minutes']} Min. KI, "
          f"{meta['api_cost_usd']:.4f} USD API Kosten, gesamt {time.monotonic() - start:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
