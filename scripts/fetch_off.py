"""Holt ca. 200 Protein- und Supplementprodukte von Open Food Facts und speichert einen Snapshot.

Nur beim ersten Aufbau noetig. Der Snapshot data/products.json liegt im Repo.
Daten: Open Food Facts, ODbL (https://world.openfoodfacts.org).
"""
import json
import sys
import time
from datetime import date
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parent.parent / "data" / "products.json"
URL = "https://world.openfoodfacts.org/cgi/search.pl"
FIELDS = ("code,product_name,generic_name,brands,ingredients_text,ingredients_text_de,allergens_tags,"
          "nutriments,serving_size,labels,lang,url")
TERMS = ["protein", "whey", "eiweiss", "proteinpulver", "casein", "kreatin", "protein riegel",
         "aminosaeuren", "bcaa", "vegan protein", "mass gainer", "pre workout", "isolate", "shake protein"]
TARGET = 200
HEADERS = {"User-Agent": "LabelLab/0.1 (Portfolio, github.com/omaraldulimay)"}


def keep(p: dict) -> bool:
    return bool(p.get("code") and (p.get("product_name") or "").strip())


def slim(p: dict) -> dict:
    n = p.get("nutriments") or {}
    keys = ["energy-kcal_100g", "fat_100g", "saturated-fat_100g", "carbohydrates_100g",
            "sugars_100g", "proteins_100g", "salt_100g"]
    return {
        "code": p["code"],
        "name": p.get("product_name", "").strip(),
        "generic_name": (p.get("generic_name") or "").strip(),
        "brand": (p.get("brands") or "").strip(),
        "labels": (p.get("labels") or "").strip(),
        "ingredients": (p.get("ingredients_text_de") or p.get("ingredients_text") or "").strip(),
        "allergens_tags": p.get("allergens_tags") or [],
        "serving_size": (p.get("serving_size") or "").strip(),
        "nutriments": {k: n[k] for k in keys if isinstance(n.get(k), (int, float))},
        "lang": p.get("lang") or "",
        "url": p.get("url") or "",
    }


def main() -> None:
    found: dict[str, dict] = {}
    with httpx.Client(headers=HEADERS, timeout=60) as client:
        for country in ("en:germany", "en:austria", None):  # deutschsprachig zuerst
            for term in TERMS:
                if len(found) >= TARGET:
                    break
                params = {"search_terms": term, "json": 1, "page_size": 100, "fields": FIELDS,
                          "sort_by": "unique_scn_n"}
                if country:
                    params.update(tagtype_0="countries", tag_contains_0="contains", tag_0=country)
                try:
                    data = client.get(URL, params=params).json()
                except Exception as exc:  # Netzwerk oder Rate Limit: weiter mit dem naechsten Begriff
                    print("Fehler", term, exc, file=sys.stderr)
                    time.sleep(3)
                    continue
                for p in data.get("products", []):
                    if keep(p) and p["code"] not in found:
                        found[p["code"]] = slim(p)
                print(f"{country} {term}: {len(found)}")
                time.sleep(1)
    products = list(found.values())[:TARGET]
    snapshot = {"source": "Open Food Facts (ODbL)", "fetched": date.today().isoformat(), "products": products}
    OUT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1))
    print("gespeichert:", len(products), "->", OUT)


if __name__ == "__main__":
    main()
