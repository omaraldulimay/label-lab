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


LMIV = "VO (EU) 1169/2011"
NUTRIENTS_EN = {"Energie": "energy", "Fett": "fat", "Kohlenhydrate": "carbohydrates", "Zucker": "sugars",
                "Eiweiß": "protein", "Salz": "salt"}
# Rechtsgrundlagen, jeweils Deutsch und Englisch
RULE_NUTRITION = (f"{LMIV} Art. 9 Abs. 1 Buchst. l, Art. 30 (Nährwertdeklaration)",
                  f"{LMIV} Art. 9(1)(l), Art. 30 (nutrition declaration)")
RULE_INGREDIENTS = (f"{LMIV} Art. 9 Abs. 1 Buchst. b, Art. 18 (Zutatenverzeichnis)",
                    f"{LMIV} Art. 9(1)(b), Art. 18 (list of ingredients)")
RULE_PORTION = (f"{LMIV} Art. 33 (Angabe je Portion)", f"{LMIV} Art. 33 (per portion expression)")
RULE_VALUES = (f"{LMIV} Art. 30 Abs. 1, Anhang XV (Darstellung der Werte)",
               f"{LMIV} Art. 30(1), Annex XV (expression of values)")
RULE_ENERGY = (f"{LMIV} Art. 31 Abs. 1, Anhang XIV (Umrechnungsfaktoren)",
               f"{LMIV} Art. 31(1), Annex XIV (conversion factors)")


def _f(check: str, code: str, severity: str, message: str, message_en: str = "",
       rule: tuple[str, str] = ("", "")) -> dict:
    return {"check": check, "code": code, "severity": severity, "message": message,
            "message_en": message_en or message, "rule": rule[0], "rule_en": rule[1]}


def check_gaps(p: dict) -> list[dict]:
    n = p.get("nutriments") or {}
    out = []
    missing = [label for key, label in NUTRIENTS.items() if n.get(key) is None]
    if missing:
        sev = "error" if len(missing) >= 4 else "warn"
        out.append(_f("luecken", "naehrwerte_fehlen", sev, "Nährwerte fehlen: " + ", ".join(missing),
                      "Nutrition values missing: " + ", ".join(NUTRIENTS_EN[m] for m in missing), RULE_NUTRITION))
    if not (p.get("ingredients") or "").strip():
        out.append(_f("luecken", "zutaten_fehlen", "error", "Zutatenliste fehlt.",
                      "Ingredient list is missing.", RULE_INGREDIENTS))
    if not (p.get("serving_size") or "").strip():
        out.append(_f("luecken", "portion_fehlt", "warn", "Portionsgröße fehlt.",
                      "Serving size is missing.", RULE_PORTION))
    return out


def check_contradictions(p: dict) -> list[dict]:
    n = p.get("nutriments") or {}
    out = []
    sugar, carbs = n.get("sugars_100g"), n.get("carbohydrates_100g")
    if sugar is not None and carbs is not None and sugar > carbs + EPS:
        out.append(_f("widersprueche", "zucker_ueber_kohlenhydrate", "error",
                      f"Zucker ({sugar} g) ist höher als Kohlenhydrate ({carbs} g).",
                      f"Sugars ({sugar} g) are higher than carbohydrates ({carbs} g).", RULE_VALUES))
    sat, fat = n.get("saturated-fat_100g"), n.get("fat_100g")
    if sat is not None and fat is not None and sat > fat + EPS:
        out.append(_f("widersprueche", "gesaettigt_ueber_fett", "error",
                      f"Gesättigte Fette ({sat} g) sind höher als Fett ({fat} g).",
                      f"Saturated fat ({sat} g) is higher than total fat ({fat} g).", RULE_VALUES))
    kcal, prot = n.get("energy-kcal_100g"), n.get("proteins_100g")
    if None not in (kcal, prot, carbs, fat):
        calc = 4 * prot + 4 * carbs + 9 * fat
        if calc > 0 and abs(kcal - calc) / calc > KCAL_TOLERANCE:
            dev = round(abs(kcal - calc) / calc * 100)
            out.append(_f("widersprueche", "kalorien_abweichung", "error",
                          f"Angegeben {kcal:g} kcal, aus den Makros berechnet {calc:.0f} kcal "
                          f"(Abweichung {dev} %).",
                          f"Declared {kcal:g} kcal, calculated from the macros {calc:.0f} kcal "
                          f"(deviation {dev} %).", RULE_ENERGY))
    for key in GRAM_FIELDS:
        v = n.get(key)
        if v is not None and v > 100:
            out.append(_f("widersprueche", "wert_ueber_100g", "error",
                          f"{key.replace('_100g', '')} ist {v} g pro 100 g, mehr als 100 g sind nicht möglich.",
                          f"{key.replace('_100g', '')} is {v} g per 100 g, more than 100 g is impossible.",
                          RULE_VALUES))
    return out
