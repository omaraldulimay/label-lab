"""Regelbasierte Pruefungen ohne KI: Luecken und Widersprueche."""

NUTRIENTS = {
    "energy-kcal_100g": "Energie",
    "fat_100g": "Fett",
    "carbohydrates_100g": "Kohlenhydrate",
    "sugars_100g": "Zucker",
    "proteins_100g": "Eiweiß",
    "salt_100g": "Salz",
}
GRAM_FIELDS = ["fat_100g", "saturated-fat_100g", "carbohydrates_100g", "sugars_100g",
               "proteins_100g", "salt_100g"]
KCAL_TOLERANCE = 0.15
EPS = 0.05  # Rundungsspielraum in Gramm


def _f(check: str, code: str, severity: str, message: str) -> dict:
    return {"check": check, "code": code, "severity": severity, "message": message}


def check_gaps(p: dict) -> list[dict]:
    n = p.get("nutriments") or {}
    out = []
    missing = [label for key, label in NUTRIENTS.items() if n.get(key) is None]
    if missing:
        sev = "error" if len(missing) >= 4 else "warn"
        out.append(_f("luecken", "naehrwerte_fehlen", sev, "Nährwerte fehlen: " + ", ".join(missing)))
    if not (p.get("ingredients") or "").strip():
        out.append(_f("luecken", "zutaten_fehlen", "error", "Zutatenliste fehlt."))
    if not (p.get("serving_size") or "").strip():
        out.append(_f("luecken", "portion_fehlt", "warn", "Portionsgröße fehlt."))
    return out


def check_contradictions(p: dict) -> list[dict]:
    n = p.get("nutriments") or {}
    out = []
    sugar, carbs = n.get("sugars_100g"), n.get("carbohydrates_100g")
    if sugar is not None and carbs is not None and sugar > carbs + EPS:
        out.append(_f("widersprueche", "zucker_ueber_kohlenhydrate", "error",
                      f"Zucker ({sugar} g) ist höher als Kohlenhydrate ({carbs} g)."))
    sat, fat = n.get("saturated-fat_100g"), n.get("fat_100g")
    if sat is not None and fat is not None and sat > fat + EPS:
        out.append(_f("widersprueche", "gesaettigt_ueber_fett", "error",
                      f"Gesättigte Fette ({sat} g) sind höher als Fett ({fat} g)."))
    kcal, prot = n.get("energy-kcal_100g"), n.get("proteins_100g")
    if None not in (kcal, prot, carbs, fat):
        calc = 4 * prot + 4 * carbs + 9 * fat
        if calc > 0 and abs(kcal - calc) / calc > KCAL_TOLERANCE:
            dev = round(abs(kcal - calc) / calc * 100)
            out.append(_f("widersprueche", "kalorien_abweichung", "error",
                          f"Angegeben {kcal:g} kcal, aus den Makros berechnet {calc:.0f} kcal "
                          f"(Abweichung {dev} %)."))
    for key in GRAM_FIELDS:
        v = n.get(key)
        if v is not None and v > 100:
            out.append(_f("widersprueche", "wert_ueber_100g", "error",
                          f"{key.replace('_100g', '')} ist {v} g pro 100 g, mehr als 100 g sind nicht möglich."))
    return out
