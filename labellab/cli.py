"""Ohne Datenbank und Docker: Snapshot pruefen und results.json schreiben.

  python -m labellab.cli            # Modus aus LLM_MODE (Standard fake)
"""
import sys
import time

from .llm import LLMError, get_llm
from .pipeline import default_cache, export_results, load_products, run_all


def main() -> int:
    llm = get_llm()
    products = load_products()
    start = time.monotonic()

    def progress(i, n, r):
        print(f"[{i}/{n}] {r['status']:6} {r['name'][:50]}  ({r['llm']['seconds']} s)", flush=True)

    try:
        results = run_all(products, llm, default_cache(llm), progress)
    except LLMError as exc:
        print("Abbruch:", exc, file=sys.stderr)
        return 1
    meta = export_results(results, llm)
    print(f"{meta['products']} Produkte, {meta['counts']}, Modell {meta['model']} ({meta['mode']}), "
          f"{meta['llm_minutes']} Min. KI, gesamt {time.monotonic() - start:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
