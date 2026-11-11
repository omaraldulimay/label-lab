"""Nährwertbezogene Angaben (Anhang VO (EG) 1924/2006): nur Python prüft sie, nie das Modell.

Jede Angabe hat Muster und Bedingung. Erfüllt: zulässig. Nicht erfüllt: Fund. Fehlen die Werte: "nicht prüfbar".
Werte je 100 g (Nährwerte aus den Produktdaten). Ballaststoffe und Calcium stehen nicht in den Daten.
"""
import re

R_NUTRITION = ("Anhang VO (EG) 1924/2006, Bedingung der nährwertbezogenen Angabe nicht erfüllt",
               "Annex to Reg. (EC) 1924/2006, condition of the nutrition claim not met")
R_UNKNOWN = ("Anhang VO (EG) 1924/2006, Bedingung der nährwertbezogenen Angabe nicht prüfbar",
             "Annex to Reg. (EC) 1924/2006, condition of the nutrition claim cannot be checked")

_ADDED_SUGAR_RE = re.compile(r"zucker|sugar|(?<![a-z])(?:glukose|glucose|fruktose|fructose|dextrose|maltodextrin|honig|honey|"
                             r"saccharose|sucrose|maltose|sucre|azúcar|zucchero)|(?:agaven|agave|ahorn|maple|reis|rice|dattel|"
                             r"date|invert)\w*[- ]?(?:sirup|syrup)", re.IGNORECASE)
_NO_SUGAR_RE = re.compile(r"zuckeralkohol\w*|sugar[- ]alcohols?|zucker(?:frei|zusatz)\w*|sugar[- ]free|"
                          r"no[- ]added[- ]sugars?|no[- ]sugars?|zuckerkul\w+|(?:enthält|contains)[^.]{0,30}(?:natur aus|naturally)[^.]{0,20}(?:zucker|sugars?)", re.IGNORECASE)


def _share(n: dict) -> float | None:
    kcal, prot = n.get("energy-kcal_100g"), n.get("proteins_100g")
    return None if not kcal or prot is None else 4 * prot / kcal * 100


def _at_most(field: str, limit: float):
    return lambda p: None if (p.get("nutriments") or {}).get(field) is None else p["nutriments"][field] <= limit


def _at_least_share(limit: float):
    return lambda p: None if _share(p.get("nutriments") or {}) is None else _share(p["nutriments"]) >= limit


def _no_added_sugar(p: dict):
    ing = p.get("ingredients") or ""
    if not ing.strip():
        return None
    return not _ADDED_SUGAR_RE.search(_NO_SUGAR_RE.sub(" ", ing))


def _unknown(_p: dict):
    return None


# key -> (Muster, Prüfung, Bedingung DE, Bedingung EN, fehlende Angabe DE, fehlende Angabe EN)
NUTRITION_CLAIMS: dict[str, tuple] = {
    "protein_high": (
        r"high[- ]?proteins?|proteinreich|eiwei(?:ß|ss)[- ]?reich|rich[- ]in[- ](?:vegetable[- ])?proteins?|"
        r"reich an (?:eiwei(?:ß|ss)|protein)\w*", _at_least_share(20),
        "mindestens 20 % der Energie aus Eiweiß", "at least 20 % of the energy from protein",
        "Eiweiß oder Energie fehlen", "protein or energy values are missing"),
    "protein_source": (
        r"source[- ]of[- ]proteins?|proteinquelle|eiwei(?:ß|ss)quelle|quelle (?:von|für) (?:eiwei(?:ß|ss)|protein)\w*",
        _at_least_share(12),
        "mindestens 12 % der Energie aus Eiweiß", "at least 12 % of the energy from protein",
        "Eiweiß oder Energie fehlen", "protein or energy values are missing"),
    "fibre_high": (
        r"high[- ]fib(?:re|er)s?|ballaststoffreich|reich an ballaststoffen|riche en fibres|rich in fib(?:re|er)s?",
        _unknown, "mindestens 6 g Ballaststoffe je 100 g", "at least 6 g fibre per 100 g",
        "Ballaststoffe stehen nicht in den Daten", "fibre is not in the data"),
    "fibre_source": (
        r"source[- ]of[- ]fib(?:re|er)s?|ballaststoffquelle|quelle von ballaststoffen",
        _unknown, "mindestens 3 g Ballaststoffe je 100 g", "at least 3 g fibre per 100 g",
        "Ballaststoffe stehen nicht in den Daten", "fibre is not in the data"),
    "calcium_source": (
        r"calcium[- ]source|source[- ]of[- ]calcium|calciumquelle|quelle von calcium",
        _unknown, "mindestens 15 % der Nährstoffbezugswerte (120 mg Calcium je 100 g)",
        "at least 15 % of the reference intake (120 mg calcium per 100 g)",
        "Calcium steht nicht in den Daten", "calcium is not in the data"),
    "sugar_none_added": (
        r"no[- ]added[- ]sugars?|without[- ]added[- ]sugars?|ohne (?:zucker ?zusatz|zugesetzten? zucker)|"
        r"keine[rn]? zugesetzten? zucker",
        _no_added_sugar, "keine zugesetzten Zucker in der Zutatenliste", "no added sugars in the ingredient list",
        "die Zutatenliste fehlt", "the ingredient list is missing"),
    "sugar_free": (
        r"(?<!oder )zuckerfrei|sugar[- ]free|no[- ]sugars?\b(?![- ]added)|ohne zucker\b(?! ?zusatz)",
        _at_most("sugars_100g", 0.5), "höchstens 0,5 g Zucker je 100 g", "at most 0.5 g sugars per 100 g",
        "Zucker fehlt", "sugars are missing"),
    "sugar_low": (
        r"low[- ]sugars?|zuckerarm(?: oder zuckerfrei)?", _at_most("sugars_100g", 5), "höchstens 5 g Zucker je 100 g",
        "at most 5 g sugars per 100 g", "Zucker fehlt", "sugars are missing"),
    "fat_free": (
        r"fat[- ]free|fettfrei", _at_most("fat_100g", 0.5), "höchstens 0,5 g Fett je 100 g",
        "at most 0.5 g fat per 100 g", "Fett fehlt", "fat is missing"),
    "fat_low": (
        r"low[- ]fat|fettarm|wenig fett", _at_most("fat_100g", 3), "höchstens 3 g Fett je 100 g",
        "at most 3 g fat per 100 g", "Fett fehlt", "fat is missing"),
}
_RES = {k: re.compile(rf"(?<![\w-])(?:{v[0]})(?![\w-])", re.IGNORECASE) for k, v in NUTRITION_CLAIMS.items()}
NUTRITION_RE = re.compile("|".join(f"(?:{r.pattern})" for r in _RES.values()), re.IGNORECASE)
FIELDS = ("name", "generic_name", "labels", "description")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def _without(text: str, phrase: str) -> str:
    """Text ohne die Angabe, Kommas und Leerzeichen bereinigt."""
    out = text.replace(phrase, " ", 1)
    out = re.sub(r"\s+,", ",", out)
    out = re.sub(r"^[\s,;:–-]+|[\s,;:–-]+$", "", out)
    return re.sub(r"(,\s*){2,}", ", ", re.sub(r"\s{2,}", " ", out))


def strip_claims(text: str) -> str:
    return NUTRITION_RE.sub(" ", text)


def check_nutrition(p: dict) -> list[dict]:
    """Je Angabe ein Eintrag: key, phrase, sentence (Fundstelle), field, status ok, fail oder unknown."""
    seen: set[str] = set()
    out = []
    for field in FIELDS:
        text = p.get(field) if field != "name" else p.get("name")
        if not text:
            continue
        for sentence in _sentences(text):
            for key, rx in _RES.items():
                m = rx.search(sentence)
                if not m or key in seen:
                    continue
                seen.add(key)
                ok = NUTRITION_CLAIMS[key][1](p)
                out.append({"key": key, "phrase": m.group(0), "sentence": sentence, "field": field,
                            "status": "unknown" if ok is None else "ok" if ok else "fail"})
    return out


def nutrition_finding(c: dict, p: dict) -> dict | None:
    """Fund zu einer geprüften Angabe, None wenn erfüllt."""
    if c["status"] == "ok":
        return None
    _, _, cond, cond_en, miss, miss_en = NUTRITION_CLAIMS[c["key"]]
    short = c["field"] != "description"
    claim = c["phrase"] if short else c["sentence"]
    rest = _without(p.get(c["field"]) or c["sentence"], c["phrase"]) if short else _without(c["sentence"], c["phrase"])
    if c["status"] == "fail":
        reason = f"Nährwertangabe nicht erfüllt. Bedingung: {cond}."
        reason_en = f"Nutrition claim not met. Condition: {cond_en}."
        return {"claim": claim, "verdict": "nicht_erfuellt", "reason": reason, "reason_en": reason_en,
                "rule": R_NUTRITION[0], "rule_en": R_NUTRITION[1],
                "suggestion": rest or "Angabe streichen", "suggestion_en": rest or "Remove the claim"}
    reason = f"Nährwertangabe nicht prüfbar. Bedingung: {cond}, aber {miss}."
    reason_en = f"Nutrition claim cannot be checked. Condition: {cond_en}, but {miss_en}."
    return {"claim": claim, "verdict": "nicht_pruefbar", "reason": reason, "reason_en": reason_en,
            "rule": R_UNKNOWN[0], "rule_en": R_UNKNOWN[1], "suggestion": "", "suggestion_en": ""}
