"""Holt ca. 1.800 echte Supplements (EU weit) von Open Food Facts und speichert einen Snapshot.

Nur beim ersten Aufbau noetig. Der Snapshot data/products.json liegt im Repo.
Daten: Open Food Facts, ODbL (https://world.openfoodfacts.org).
Rate Limits: Pause zwischen Anfragen, Wiederholung mit wachsender Wartezeit, eigener User-Agent.
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
          "nutriments,serving_size,labels,categories_tags,countries_tags,lang,url")
# Zielmaerkte (Tag, Kurzcode), deutschsprachige zuerst
COUNTRIES = [("en:germany", "de"), ("en:austria", "at"), ("en:switzerland", "ch"), ("en:france", "fr"),
             ("en:netherlands", "nl"), ("en:belgium", "be"), ("en:italy", "it"), ("en:spain", "es"),
             ("en:poland", "pl"), ("en:united-kingdom", "uk"), ("en:ireland", "ie"), ("en:sweden", "se"),
             ("en:denmark", "dk"), ("en:portugal", "pt"), ("en:czech-republic", "cz")]
TERMS = [  # (Suchbegriff, Kategorie). Ist die Kategorie voll, wird der Begriff uebersprungen.
    ("creatin", "creatin"), ("creatine monohydrate", "creatin"), ("kreatin", "creatin"), ("creatine", "creatin"),
    ("protein riegel", "riegel"), ("protein bar", "riegel"), ("barre proteinee", "riegel"),
    ("barretta proteica", "riegel"),
    ("aminosaeuren", "amino"), ("amino acids", "amino"), ("bcaa", "amino"), ("eaa", "amino"),
    ("l-carnitin", "amino"), ("glutamin", "amino"), ("beta alanin", "pre"), ("pre workout", "pre"),
    ("omega 3", "omega"), ("collagen", "kollagen"), ("kollagen", "kollagen"), ("mass gainer", "gainer"),
    ("vitamin c", "vitamine"), ("vitamin d3", "vitamine"), ("magnesium", "vitamine"), ("multivitamin", "vitamine"),
    ("zink", "vitamine"), ("zinc", "vitamine"),
    ("whey protein", "protein"), ("whey isolate", "protein"), ("proteinpulver", "protein"),
    ("eiweisspulver", "protein"), ("casein", "protein"), ("vegan protein", "protein"), ("isolate", "protein"),
    ("protein shake pulver", "protein"), ("proteine", "protein"), ("proteina", "protein"),
    ("poudre de proteine", "protein"), ("eiwitpoeder", "protein"), ("bialko odzywka", "protein"),
]
PAGES = 8
TARGET = 1800
PER_COUNTRY = 400  # Obergrenze je Zielmarkt, damit nicht ein Land alles belegt
PAUSE = 2.0
HEADERS = {"User-Agent": "LabelLab/1.0 portfolio project"}


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
    r"mehl\b|flour|wrap|tortilla|ice cream|\beis\b|döner|"
    # weitere Sprachen: Milchprodukte, Fertiggerichte, Getraenke, Gebaeck
    r"yaourt|fromage|\blait\b|boisson|biscuit|gâteau|gateau|céréales|cereales|céréale|jambon|poulet|"
    r"\bpâtes|yoghurt|\bkaas|melk|\bdrank|koek|ontbijt|wafel|"
    r"formaggio|\blatte\b|bevanda|biscotti|cereali|pane\b|\bqueso|\bleche\b|bebida|galleta|pan\b|"
    r"jogurt|ser\b|\bmleko|napój|ciastk|baton\s+zbożowy|kanapk|"
    r"chocolate\s+bar|schokoriegel|müsliriegel|muesliriegel|cereal\s+bar|flapjack|granola|"
    r"\bwater\b|\bwasser\b|\beau\b|juice|\bsaft\b|\bjus\b|kladdkaka|\bcake|kuchen|margarin|\bbeurre|butter\b|"
    r"demi[\s-]sel|\bsmoothie|\bshot\b|"
    r"cocktail|beer|wine|\bbier\b|\bwein\b|kaffee|coffee|\btea\b|\btee\b",
    re.IGNORECASE)
CATEGORIES = [  # (Name, Muster, Hoechstzahl), Reihenfolge zaehlt
    ("riegel", re.compile(r"riegel|\bbars?\b|barre|barrette|barretta|barrita|baton|reep|repen", re.I), 330),
    ("creatin", re.compile(r"creatin|kreatin|creapure|créatine|creatina", re.I), 160),
    ("pre", re.compile(r"pre[\s-]?workout|booster|citrullin|beta[\s-]?alanin|koffein|caffeine", re.I), 110),
    ("amino", re.compile(r"bcaa|eaa\b|amino|glutamin|carnitin|arginin|acides? aminés|aminoácid|aminokwas", re.I), 160),
    ("kollagen", re.compile(r"collagen|kollagen|collagène|colágeno|kolagen", re.I), 80),
    ("omega", re.compile(r"omega|fish oil|fischöl|huile de poisson|krill|dha\b|epa\b", re.I), 100),
    ("vitamine", re.compile(r"vitamin|multivitamin|magnesium|magnésium|zink|zinc|kapsel|capsule|gélule|"
                            r"tablet|compresse|comprimid|komplex|calcium|eisen|iron|selen", re.I), 330),
    ("gainer", re.compile(r"gainer|mass\s*(?:weight|gain)|weight\s*gainer", re.I), 70),
    ("protein", re.compile(r"whey|molke|casein|kasein|isolat|protein|gainer|eiwei|białk|odżywk|"
                           r"proteina|proteína|protéine|proteine|eiwit|proteiner", re.I), 600),
]
CAT_LIMIT = {n: m for n, _, m in CATEGORIES}


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


def market(p: dict) -> str:
    """Erster Zielmarkt (in COUNTRIES Reihenfolge), in dem das Produkt gelistet ist, sonst leer."""
    tags = set(p.get("countries_tags") or [])
    return next((cc for tag, cc in COUNTRIES if tag in tags), "")


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
        "country": market(p),
        "url": p.get("url") or "",
    }


def fetch(client: httpx.Client, params: dict) -> dict | None:
    """Eine Anfrage mit Wiederholung: bei Fehler oder Rate Limit (429, 5xx) warten und neu versuchen."""
    for attempt in range(5):
        try:
            # Bei 503 liefert der Cache dieselbe Fehlerseite fuer dieselbe URL, darum ab dem 2. Versuch eine
            # unbenutzte Zusatzangabe anhaengen (wird vom Server ignoriert)
            r = client.get(URL, params=params if attempt == 0 else {**params, "retry": f"{time.time():.0f}"})
            if r.status_code in (429, 500, 502, 503, 504):
                raise RuntimeError(f"HTTP {r.status_code}")
            return r.json()
        except Exception as exc:
            wait = 3 * 2 ** attempt
            print("Fehler", params.get("search_terms"), exc, f"(warte {wait} s)", file=sys.stderr)
            time.sleep(wait)
    return None


def main() -> None:
    found: dict[str, dict] = {}   # Schluessel ist der Code, damit gibt es keine Duplikate
    per_country: dict[str, int] = {}
    count = lambda cat: sum(1 for q in found.values() if q["category"] == cat)  # noqa: E731
    with httpx.Client(headers=HEADERS, timeout=60, follow_redirects=True) as client:
        # Ohne Laenderfilter suchen (die Filteranfragen scheitern oft mit 503), das Land steht in countries_tags.
        # Die API liefert hoechstens 100 Treffer pro Seite, darum mehrere Seiten je Begriff.
        for term, term_cat in TERMS:
            for page in range(1, PAGES + 1):
                if len(found) >= TARGET or count(term_cat) >= CAT_LIMIT[term_cat]:
                    break
                params = {"search_terms": term, "json": 1, "page_size": 100, "page": page, "fields": FIELDS,
                          "sort_by": "unique_scans_n"}
                data = fetch(client, params)
                time.sleep(PAUSE)
                if data is None:
                    continue
                for p in data.get("products", []):
                    code = str(p.get("code") or "")
                    cc = market(p)
                    if not cc or code in found or not keep(p) or per_country.get(cc, 0) >= PER_COUNTRY:
                        continue  # nur Produkte, die in einem Zielmarkt gelistet sind
                    cat = category(p)
                    if count(cat) >= CAT_LIMIT[cat]:
                        continue
                    found[code] = slim(p) | {"category": cat}
                    per_country[cc] = per_country.get(cc, 0) + 1
                print(f"{term} S{page}: {len(found)} {per_country}", flush=True)
                if len(data.get("products", [])) < 100:
                    break
    products = list(found.values())[:TARGET]
    snapshot = {"source": "Open Food Facts (ODbL)", "fetched": date.today().isoformat(), "products": products}
    OUT.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")))
    print("gespeichert:", len(products), "->", OUT)


if __name__ == "__main__":
    main()
