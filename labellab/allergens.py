"""14 EU-Hauptallergene (Verordnung 1169/2011) mit Synonymen in Deutsch und Englisch.

Ein Begriff passt, wenn er am Wortanfang steht (so trifft "molke" auch "Molkenprotein").
Begriffe mit "=" am Ende muessen das ganze Wort sein (so trifft "ei=" nicht "Eiweiss").
"""
import re

ALLERGENS: dict[str, dict] = {
    "gluten": {"label": "Gluten", "off": ["en:gluten"], "terms": [
        "gluten", "weizen", "dinkel", "roggen", "gerste", "hafer", "kamut", "malz", "wheat",
        "barley", "rye", "oat", "spelt", "semolina", "grieß", "griess"]},
    "krebstiere": {"label": "Krebstiere", "off": ["en:crustaceans"], "terms": [
        "krebstier", "krebs=", "garnele", "krabbe", "hummer", "shrimp", "crab", "lobster",
        "crustacean", "langustine", "krill"]},
    "eier": {"label": "Eier", "off": ["en:eggs"], "terms": [
        "ei=", "eier=", "hühnerei", "huehnerei", "vollei", "eigelb", "eiklar", "eipulver",
        "eiprotein", "eiweißpulver", "ovalbumin", "egg", "albumin=", "hühnereiweiß"]},
    "fisch": {"label": "Fisch", "off": ["en:fish"], "terms": [
        "fisch", "lachs", "thunfisch", "kabeljau", "hering", "anchovis", "sardine", "fish",
        "salmon", "tuna", "cod=", "anchov"]},
    "erdnuesse": {"label": "Erdnüsse", "off": ["en:peanuts"], "terms": [
        "erdnuss", "erdnüsse", "erdnuß", "peanut", "arachis"]},
    "soja": {"label": "Soja", "off": ["en:soybeans"], "terms": [
        "soja", "soy", "tofu", "edamame", "sojalecithin"]},
    "milch": {"label": "Milch", "off": ["en:milk"], "terms": [
        "milch", "molke", "casein", "kasein", "caseinat", "laktose", "lactose", "whey", "milk",
        "sahne", "butter", "joghurt", "yoghurt", "quark", "kefir", "käse", "kaese", "cheese",
        "laktalbumin", "lactalbumin", "lactoglobulin", "laktoglobulin", "rahm", "milchzucker",
        "buttermilch", "cream", "skyr", "milcheiweiß", "milcheiweiss"]},
    "schalenfruechte": {"label": "Schalenfrüchte", "off": ["en:nuts"], "terms": [
        "mandel", "haselnuss", "haselnüsse", "walnuss", "walnüsse", "cashew", "pistazie",
        "pekannuss", "pecan", "paranuss", "macadamia", "almond", "hazelnut", "walnut",
        "pistachio", "schalenfrucht", "nuss=", "nüsse=", "nuts="]},
    "sellerie": {"label": "Sellerie", "off": ["en:celery"], "terms": ["sellerie", "celery"]},
    "senf": {"label": "Senf", "off": ["en:mustard"], "terms": ["senf", "mustard"]},
    "sesam": {"label": "Sesam", "off": ["en:sesame-seeds"], "terms": ["sesam", "sesame", "tahini"]},
    "sulfite": {"label": "Schwefeldioxid und Sulfite", "off": ["en:sulphur-dioxide-and-sulphites"],
                "terms": ["sulfit", "sulphite", "sulfite", "schwefeldioxid", "sulphur dioxide",
                          "sulfur dioxide", "e220", "e221", "e222", "e223", "e224", "e226", "e227", "e228"]},
    "lupine": {"label": "Lupinen", "off": ["en:lupin"], "terms": ["lupine", "lupin"]},
    "weichtiere": {"label": "Weichtiere", "off": ["en:molluscs"], "terms": [
        "weichtier", "muschel", "tintenfisch", "auster", "schnecke", "mollus", "squid", "oyster",
        "mussel", "calamari"]},
}

_OFF_TO_KEY = {tag: key for key, a in ALLERGENS.items() for tag in a["off"]}


def _compile(terms: list[str]) -> re.Pattern:
    parts = []
    for t in terms:
        if t.endswith("="):
            parts.append(rf"(?<![\w]){re.escape(t[:-1])}(?![\w])")
        else:
            parts.append(rf"(?<![\w]){re.escape(t)}")
    return re.compile("|".join(parts), re.IGNORECASE)


_PATTERNS = {key: _compile(a["terms"]) for key, a in ALLERGENS.items()}


def find_in_text(text: str) -> dict[str, str]:
    """Allergen-Schluessel -> erster Treffer im Text."""
    found = {}
    for key, pat in _PATTERNS.items():
        m = pat.search(text or "")
        if m:
            found[key] = m.group(0)
    return found


def from_off_tags(tags: list[str]) -> set[str]:
    return {_OFF_TO_KEY[t] for t in tags if t in _OFF_TO_KEY}


_TRACES = re.compile(
    r"(kann|können|koennen)[^.\n]*spuren[^.\n]*|spuren\s+(von|enthalten)[^.\n]*|may contain[^.\n]*|"
    r"traces\s+of[^.\n]*|hergestellt\s+in\s+einem[^.\n]*|produced\s+in\s+a[^.\n]*", re.IGNORECASE)


def strip_traces(text: str) -> str:
    """Spurenhinweise ("Kann Spuren von ... enthalten") sind keine Zutaten."""
    return _TRACES.sub(" ", text or "")


def check_allergens(ingredients: str, allergens_tags: list[str]) -> list[dict]:
    """Zutaten gegen deklarierte Allergene abgleichen."""
    if not (ingredients or "").strip():
        return []  # ohne Zutaten ist kein Abgleich moeglich, die Luecke meldet eine andere Regel
    in_text = find_in_text(strip_traces(ingredients))
    anywhere = find_in_text(ingredients)
    declared = from_off_tags(allergens_tags or [])
    out = []
    for key, hit in in_text.items():
        if key not in declared:
            out.append({"check": "allergene", "code": "allergen_nicht_deklariert", "severity": "error",
                        "message": f"Zutaten nennen \"{hit}\" ({ALLERGENS[key]['label']}), "
                                   f"das Allergen ist nicht deklariert."})
    for key in declared - set(anywhere):
        out.append({"check": "allergene", "code": "allergen_ohne_zutat", "severity": "warn",
                    "message": f"{ALLERGENS[key]['label']} ist deklariert, aber in den Zutaten "
                               f"nicht zu finden."})
    return out
