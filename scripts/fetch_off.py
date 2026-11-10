"""Holt ca. 200 Protein- und Supplementprodukte von Open Food Facts und speichert einen Snapshot.

Nur beim ersten Aufbau noetig. Der Snapshot data/products.json liegt im Repo.
Daten: Open Food Facts, ODbL (https://world.openfoodfacts.org).
"""
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parent.parent / "data" / "products.json"
URL = "https://world.openfoodfacts.org/cgi/search.pl"
FIELDS = ("code,product_name,generic_name,brands,ingredients_text,ingredients_text_de,allergens_tags,"
          "nutriments,serving_size,labels,categories_tags,lang,url")
TERMS = ["whey protein", "whey isolate", "proteinpulver", "eiweisspulver", "casein", "creatin", "kreatin",
         "protein riegel", "protein bar", "aminosaeuren", "bcaa", "eaa", "vegan protein", "mass gainer",
         "pre workout", "isolate", "vitamin c kapseln", "vitamin d3", "magnesium kapseln", "omega 3 kapseln",
         "multivitamin", "zink kapseln", "l-carnitin", "glutamin", "beta alanin", "protein shake pulver"]
TARGET = 200
HEADERS = {"User-Agent": "LabelLab/0.1 (Portfolio, github.com/omaraldulimay)"}


# Nur echte Supplements: Proteinpulver, Riegel, Creatin, Aminosaeuren, Vitamine und Kapseln, Pre Workout.
INCLUDE = re.compile(
    r"whey|molkenprotein|molkeneiwei|isolat|isolate|casein|kasein|proteinpulver|eiweisspulver|eiweißpulver|"
    r"protein\s*(powder|pulver|shake|riegel|bar|crisp)|(riegel|bar)\b.*protein|protein.*(riegel|bar)\b|"
    r"vegan\s*protein|mass\s*gainer|gainer|creatin|kreatin|creapure|bcaa|eaa\b|amino|glutamin|glutamine|"
    r"carnitin|beta[\s-]?alanin|citrullin|arginin|pre[\s-]?workout|booster|vitamin|multivitamin|magnesium|"
    r"zink|zinc|omega|kapsel|capsule|tablette|tablet|kurkuma|ashwagandha|coffein|caffeine|electrolyt|"
    r"collagen|kollagen|erbsenprotein|reisprotein|hanfprotein|sojaprotein|protein\s*\d|protein\b",
    re.IGNORECASE)
EXCLUDE = re.compile(
    r"linse|bohne|bean|kicherbse|hummus|nudel|pasta|\bbrot|bread|müsli|muesli|joghurt|yogurt|jogurt|quark|skyr|"
    r"käse|cheese|\bmilch|\bmilk|drink|getränk|suppe|soup|salat|burger|bratling|schnitzel|wurst|fleisch|chips|"
    r"tofu|tempeh|seitan|porridge|pudding|dessert|aufstrich|spread|sauce|soße|döner|kebab|frika|bites|"
    r"monster|energy|waffel|waffle|cookie|brownie\b|\bballs?\b|crispies|snack|gummies|huel|yfood|flavour$|"
    r"mehl\b|flour|wrap|tortilla|ice cream|\beis\b|döner",
    re.IGNORECASE)
CATEGORIES = [  # (Name, Muster, Hoechstzahl), Reihenfolge zaehlt
    ("riegel", re.compile(r"riegel|\bbar\b", re.I), 45),
    ("creatin", re.compile(r"creatin|kreatin|creapure", re.I), 25),
    ("pre", re.compile(r"pre[\s-]?workout|booster|citrullin|beta[\s-]?alanin|koffein|caffeine", re.I), 20),
    ("amino", re.compile(r"bcaa|eaa\b|amino|glutamin|carnitin|arginin", re.I), 20),
    ("vitamine", re.compile(r"vitamin|multivitamin|magnesium|zink|zinc|omega|kapsel|capsule|tablet|komplex", re.I), 30),
    ("protein", re.compile(r"whey|molke|casein|kasein|isolat|protein|gainer|eiwei", re.I), 70),
]


def category(p: dict) -> str | None:
    text = " ".join([p.get("product_name") or "", p.get("generic_name") or ""])
    for name, pat, _ in CATEGORIES:
        if pat.search(text):
            return name
    return None


def keep(p: dict) -> bool:
    if not (p.get("code") and (p.get("product_name") or "").strip()):
        return False
    text = " ".join([p.get("product_name") or "", p.get("generic_name") or ""])
    if EXCLUDE.search(text):
        return False
    return category(p) is not None


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
                data = None
                for attempt in range(4):  # Rate Limit: warten und neu versuchen
                    try:
                        data = client.get(URL, params=params).json()
                        break
                    except Exception as exc:
                        print("Fehler", term, exc, file=sys.stderr)
                        time.sleep(5 * (attempt + 1))
                if data is None:
                    continue
                for p in data.get("products", []):
                    if keep(p) and p["code"] not in found:
                        cat = category(p)
                        limit = next(m for n, _, m in CATEGORIES if n == cat)
                        if sum(1 for q in found.values() if q["category"] == cat) < limit:
                            found[p["code"]] = slim(p) | {"category": cat}
                print(f"{country} {term}: {len(found)}")
                time.sleep(2)
    products = list(found.values())[:TARGET]
    snapshot = {"source": "Open Food Facts (ODbL)", "fetched": date.today().isoformat(), "products": products}
    OUT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1))
    print("gespeichert:", len(products), "->", OUT)


if __name__ == "__main__":
    main()
