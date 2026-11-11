"""Claim Pruefung: Python Vorfilter plus ein Modell (Claude Haiku oder Ollama) oder der Fake.

Ablauf pro Produkt:
1. Produkttext in Saetze zerlegen.
2. Saetze, die einem zugelassenen EU Health Claim entsprechen, sind zulaessig und gehen nicht ans Modell.
3. Nährwertangabe "proteinreich" prueft Python selbst (Eiweissanteil an der Energie).
4. Nur verdaechtige Saetze (Keyword Heuristik) gehen in EINEM Aufruf an das Modell.
5. Das Modell liefert pro Satz Urteil, rule_id, Grund und Ersatz. Regeltexte kommen aus RULES.
Ergebnisse werden per Hash der verdaechtigen Saetze gecacht.
"""
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

PROMPT_VERSION = "3"
DEFAULT_MODEL = "qwen2.5:3b"  # Ollama
DEFAULT_CLAUDE_MODEL = "claude-haiku-5-5"
DEFAULT_URL = "http://localhost:11434"
VERDICTS = {"zulaessig", "unzulaessig"}

# USD pro Million Token (Claude Haiku 5.5, Prompts bis 100K Token). Cache Schreiben 1,25 x, Lesen 0,1 x.
PRICE_IN = 0.10
PRICE_OUT = 0.50
CACHE_WRITE_FACTOR = 1.25
CACHE_READ_FACTOR = 0.10
BUDGET_USD = 0.30  # harte Grenze pro Lauf

# Rechtsgrundlagen: rule_id -> (Deutsch, Englisch, Hinweis fuer das Modell)
RULES = {
    "NOT_AUTH": ("Art. 10 Abs. 1 VO (EG) 1924/2006, nicht zugelassene Angabe",
                 "Art. 10(1) Reg. (EC) 1924/2006, claim not authorised",
                 "gesundheitsbezogene Wirkversprechen, die nicht im EU Register zugelassen sind "
                 "(Fettverbrennung, Entgiftung, Immunsystem stärken, Stoffwechsel anheizen, Muskelaufbau versprechen)"),
    "DISEASE": ("Art. 7 Abs. 3 VO (EU) 1169/2011, Krankheitsbezug",
                "Art. 7(3) Reg. (EU) 1169/2011, reference to disease",
                "Aussagen, die Krankheiten verhindern, behandeln oder heilen oder auf Krankheiten verweisen "
                "(Depression, Herzinfarkt, Erkältung, Bluthochdruck, Cholesterin senken)"),
    "WEIGHT_RATE": ("Art. 12 Buchst. b VO (EG) 1924/2006, Gewichtsverlust",
                    "Art. 12(b) Reg. (EC) 1924/2006, weight loss",
                    "Gewichtsverlust in bestimmter Menge oder Zeit (zum Beispiel 5 kg in 2 Wochen)"),
    "DOCTOR": ("Art. 12 Buchst. c VO (EG) 1924/2006, Empfehlung von Ärzten",
               "Art. 12(c) Reg. (EC) 1924/2006, recommendation of doctors",
               "Verweis auf Empfehlungen einzelner Ärzte oder Gesundheitsberufe"),
    "MISLEADING": ("Art. 3 Buchst. a VO (EG) 1924/2006, irreführende Angabe",
                   "Art. 3(a) Reg. (EC) 1924/2006, misleading claim",
                   "Garantien, erfundene Zahlen oder übertriebene Superlative zur Wirkung"),
}
# Nur Python: Nährwertbezogene Angabe "proteinreich", Bedingung nicht erfüllt
R_NUTRITION = ("Art. 8 Abs. 1 VO (EG) 1924/2006 und Anhang, Bedingung nicht erfüllt",
               "Art. 8(1) Reg. (EC) 1924/2006 and Annex, condition not met")
NO_RULE = "KEINE"
MODEL_RULE_IDS = list(RULES)


def system_prompt(english: bool) -> str:
    rules = "\n".join(f"- {rid}: {hint}" for rid, (_, _, hint) in RULES.items())
    en_fields = (', "reason_en": "same sentence in English", "suggestion_en": "same sentence in English"'
                 if english else "")
    return f"""Du prüfst einzelne Werbesätze auf Supplements und Proteinprodukten nach EU Recht \
(VO (EG) 1924/2006, VO (EU) 1169/2011). Die Sätze wurden vorab als verdächtig eingestuft. \
Zugelassene Standardformulierungen sind schon aussortiert.

Pro Satz entscheidest du:
- verdict "unzulaessig": Der Satz enthält ein Wirkversprechen, einen Krankheitsbezug oder eine Garantie.
- verdict "zulaessig": Der Satz ist eine Sachangabe, eine Zubereitung oder eine neutrale Aussage.
- rule_id (nur bei unzulaessig, sonst "{NO_RULE}"), genau eine dieser IDs:
{rules}
- reason: ein kurzer deutscher Satz, warum.
- suggestion: ein zulässiger deutscher Ersatzsatz, der den Satz ersetzen kann (bei zulaessig leer).

Antworte nur mit JSON: {{"verdicts": [{{"id": 1, "verdict": "...", "rule_id": "...", "reason": "...", \
"suggestion": "..."{en_fields}}}]}}
Gib für jeden Satz genau einen Eintrag mit seiner Nummer als id. Erfinde keine Sätze."""


def verdict_schema() -> dict:
    str_ = {"type": "string"}
    props = {"id": {"type": "integer"}, "verdict": {"type": "string", "enum": sorted(VERDICTS)},
             "rule_id": {"type": "string", "enum": [*MODEL_RULE_IDS, NO_RULE]},
             "reason": str_, "reason_en": str_, "suggestion": str_, "suggestion_en": str_}
    item = {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}
    return {"type": "object", "additionalProperties": False, "required": ["verdicts"],
            "properties": {"verdicts": {"type": "array", "items": item}}}


class LLMError(RuntimeError):
    pass


class BudgetExceeded(LLMError):
    """Die geschaetzten Kosten des Laufs wuerden die harte Grenze ueberschreiten."""


@dataclass
class LLMResult:
    findings: list[dict]
    model: str
    mode: str
    tokens_in: int = 0
    tokens_out: int = 0
    seconds: float = 0.0
    cached: bool = False
    error: str = ""
    cost_usd: float = 0.0
    allowed: int = 0      # Saetze, die einem zugelassenen Claim entsprechen (nicht ans Modell)
    suspicious: int = 0   # Saetze, die ans Modell gingen


@dataclass
class Reply:
    verdicts: list[dict]
    tokens_in: int = 0
    tokens_out: int = 0
    seconds: float = 0.0
    cost_usd: float = 0.0


def product_text(p: dict) -> str:
    """Text, in dem Werbeaussagen stehen koennen."""
    parts = [p.get("name"), p.get("generic_name"), p.get("labels"), p.get("description")]
    return "\n".join(x.strip() for x in parts if x and x.strip())


def protein_share(p: dict) -> float | None:
    n = p.get("nutriments") or {}
    kcal, prot = n.get("energy-kcal_100g"), n.get("proteins_100g")
    if not kcal or prot is None:
        return None
    return round(4 * prot / kcal * 100, 1)


# ---- Vorfilter -------------------------------------------------------------------------------

def split_sentences(text: str) -> list[str]:
    """Saetze als woertliche Teilstrings des Textes (wichtig fuer "Korrektur uebernehmen")."""
    out, seen = [], set()
    for s in re.split(r"(?<=[.!?])\s+|\n+", text):
        s = s.strip()
        if len(s) >= 3 and s not in seen:
            seen.add(s)
            out.append(s)
    return out


# Zugelassene Health Claims (Auswahl aus VO (EU) 432/2012 und 1924/2006). Nährstoff -> Funktionen.
ALLOWED_CLAIMS: list[tuple[str, list[str]]] = [
    (r"(?:protein|eiweiß|eiweiss)", [
        r"zu einer zunahme an muskelmasse", r"zum erhalt (?:von|der) muskelmasse",
        r"zur erhaltung (?:von|der) muskelmasse", r"zur erhaltung normaler knochen"]),
    (r"vitamin c", [
        r"zur verringerung von müdigkeit und ermüdung", r"zu einer normalen funktion des immunsystems",
        r"zum schutz der zellen vor oxidativem stress", r"zu einer normalen kollagenbildung",
        r"zu einem normalen energiestoffwechsel", r"zu einer normalen funktion des nervensystems"]),
    (r"vitamin d(?:3)?", [
        r"zur erhaltung normaler knochen", r"zur erhaltung normaler zähne",
        r"zu einer normalen funktion des immunsystems", r"zur erhaltung einer normalen muskelfunktion",
        r"zu einem normalen calciumspiegel im blut"]),
    (r"vitamin k(?:2)?", [r"zur erhaltung normaler knochen", r"zu einer normalen blutgerinnung"]),
    (r"vitamin b(?:6|12)", [
        r"zu einem normalen (?:eiweiß- und glycogenstoffwechsel|energiestoffwechsel)",
        r"zur verringerung von müdigkeit und ermüdung", r"zu einer normalen funktion des immunsystems",
        r"zu einer normalen funktion des nervensystems"]),
    (r"zink", [
        r"zu einer normalen funktion des immunsystems", r"zum schutz der zellen vor oxidativem stress",
        r"zur erhaltung normaler haut", r"zur erhaltung normaler haare", r"zur erhaltung normaler nägel",
        r"zur erhaltung normaler knochen"]),
    (r"magnesium", [
        r"zu einer normalen muskelfunktion", r"zur verringerung von müdigkeit und ermüdung",
        r"zu einer normalen funktion des nervensystems", r"zu einem normalen energiestoffwechsel",
        r"zu einer normalen eiweißsynthese", r"zur erhaltung normaler knochen"]),
    (r"calcium", [r"zu einer normalen muskelfunktion", r"zur erhaltung normaler knochen"]),
    (r"eisen", [r"zur verringerung von müdigkeit und ermüdung", r"zu einer normalen blutbildung"]),
    (r"(?:omega[ -]?3(?:[ -]fettsäuren)?|dha(?: und epa)?|epa(?: und dha)?)", [
        r"zur erhaltung einer normalen gehirnfunktion", r"zur erhaltung normaler sehkraft",
        r"zu einer normalen herzfunktion"]),
]
# Dieselben Claims auf Englisch (EU Register Wortlaut). Nährstoff -> Funktionen.
ALLOWED_CLAIMS_EN: list[tuple[str, list[str]]] = [
    (r"protein", [
        r"a growth in muscle mass", r"the maintenance of muscle mass", r"the maintenance of normal bones"]),
    (r"vitamin c", [
        r"the reduction of tiredness and fatigue", r"the normal function of the immune system",
        r"the protection of cells from oxidative stress", r"normal collagen formation",
        r"normal energy[- ]yielding metabolism", r"the normal function of the nervous system"]),
    (r"vitamin d3?", [
        r"the maintenance of normal bones", r"the maintenance of normal teeth",
        r"the normal function of the immune system", r"the maintenance of normal muscle function",
        r"the normal absorption/utilisation of calcium and phosphorus", r"normal blood calcium levels"]),
    (r"vitamin k2?", [r"the maintenance of normal bones", r"normal blood clotting"]),
    (r"vitamin b(?:6|12)", [
        r"normal (?:protein and glycogen|energy[- ]yielding) metabolism",
        r"the reduction of tiredness and fatigue", r"the normal function of the immune system",
        r"the normal function of the nervous system"]),
    (r"zinc", [
        r"the normal function of the immune system", r"the protection of cells from oxidative stress",
        r"the maintenance of normal skin", r"the maintenance of normal hair", r"the maintenance of normal nails",
        r"the maintenance of normal bones"]),
    (r"magnesium", [
        r"normal muscle function", r"the reduction of tiredness and fatigue",
        r"the normal function of the nervous system", r"normal energy[- ]yielding metabolism",
        r"normal protein synthesis", r"the maintenance of normal bones"]),
    (r"calcium", [r"normal muscle function", r"the maintenance of normal bones"]),
    (r"iron", [r"the reduction of tiredness and fatigue", r"normal formation of red blood cells"]),
    (r"(?:omega[ -]?3(?: fatty acids)?|dha(?: and epa)?|epa(?: and dha)?)", [
        r"the maintenance of normal brain function", r"the maintenance of normal vision",
        r"the normal function of the heart"]),
]
_ALLOWED_RE = re.compile("|".join(
    rf"\b{nut}\s+(?:trägt|tragen)\s+(?:{'|'.join(funcs)})(?:\s+bei)?" for nut, funcs in ALLOWED_CLAIMS
) + "|" + "|".join(
    rf"\b{nut}\s+contribut(?:es?|ing)\s+to\s+(?:{'|'.join(funcs)})" for nut, funcs in ALLOWED_CLAIMS_EN
) + r"|\b(?:kreatin|creatin)\s+erhöht\s+die\s+körperliche\s+leistung\s+bei\s+kurzzeitigen,?\s+"
    r"intensiven\s+(?:und\s+aufeinanderfolgenden\s+)?\w+"
    r"|\bcreatine\s+increases\s+physical\s+performance\s+in\s+successive\s+bursts\s+of\s+short[- ]term,?\s+"
    r"high[- ]intensity\s+exercise", re.IGNORECASE)

# Verdaechtig: Wirkversprechen, Krankheit, Immun, Fettabbau, Garantien, Ergebnisse, Schutz, Detox, Stoffwechsel
SUSPICIOUS_RE = re.compile(
    r"verbrenn\w*|fat\s?burn\w*|abnehm\w*|schlank\w*|körperfett|fettabbau|fettpölster\w*|heil(?:t|en|end\w*|ung)\b|"
    r"linder\w*|vorbeug\w*|beugt\w*|senkt|senkung|krank\w*|krankheit\w*|erkältung\w*|infekt\w*|depression\w*|"
    r"angst\w*|schlafstör\w*|blutdruck|cholesterin\w*|herzinfarkt|schlaganfall|schmerz\w*|immun\w*|"
    r"garantier\w*|nachweislich|klinisch|studien\w*|ergebnis\w*|wirkt|wirkung\w*|schütz\w*|schutz\s+vor|"
    r"detox\w*|entgift\w*|stoffwechsel|stärkt|anheiz\w*|heizt|muskelaufbau|muskelwachstum|muskeln\s+aufbauen|"
    r"um\s+bis\s+zu|zehnmal|sichtbar\w*|kein\w*\s+muskelkater|wunder\w*|doppelt\s+so|"
    # Englisch (und einzelne Stichwoerter aus FR, ES, IT)
    r"immune|immunity|fat[- ]?burn\w*|burns?\s+fat|lose\s+weight|weight[- ]loss|slimming|\bcures?\b|\bcured\b|"
    r"\bheals?\b|healing|prevent\w*|\btreat(?:s|ment|ing)?\b|relie[fv]\w*|alleviat\w*|guarante\w*|"
    r"detox\w*|metabolism|metabolic|clinically|scientifically\s+proven|\bproven\b|\bstudies\b|"
    r"lowers?\b|reduces?\s+(?:cholesterol|blood|risk|inflammation)|cholesterol|blood\s+(?:pressure|sugar)|"
    r"disease\w*|cancer|diabetes|arthritis|depress\w*|anxiety|inflammat\w*|insomnia|"
    r"build(?:s|ing)?\s+(?:lean\s+)?muscle|muscle\s+(?:growth|gain|building)|miracle|"
    r"\bboosts?\s+(?:your\s+)?(?:immun\w*|metabolism|testosterone)|testosteron\w*|anti[- ]?aging|"
    r"inmun\w*|adelgaz\w*|quema\s+grasa|brûle\w*\s+(?:les\s+)?graisses|minceur|perte\s+de\s+poids|"
    r"dimagr\w*|brucia\w*\s+grass\w*|odchudz\w*|spala\w*\s+tłuszcz",
    re.IGNORECASE)
NUTRITION_CLAIM_RE = re.compile(r"proteinreich|high\s?protein|rich\s+in\s+protein|eiweißreich|eiweissreich", re.IGNORECASE)
PROTEIN_RICH_MIN = 20.0  # % der Energie aus Eiweiß (VO 1924/2006 Anhang)


@dataclass
class Prefilter:
    allowed: list[str]
    suspicious: list[str]
    local_findings: list[dict]


def prefilter(p: dict) -> Prefilter:
    pre = Prefilter([], [], [])
    share = protein_share(p)
    for s in split_sentences(product_text(p)):
        if NUTRITION_CLAIM_RE.search(s):  # Python rechnet, kein Modell
            if share is not None and share >= PROTEIN_RICH_MIN:
                pre.allowed.append(s)
            else:
                pre.local_findings.append(_nutrition_finding(s, share))
            continue
        rest = _ALLOWED_RE.sub(" ", s)
        if rest != s and not SUSPICIOUS_RE.search(rest):
            pre.allowed.append(s)
        elif SUSPICIOUS_RE.search(rest):
            pre.suspicious.append(s)
    return pre


def _nutrition_finding(sentence: str, share: float | None) -> dict:
    known = f"nur {share} %" if share is not None else "unbekannt"
    known_en = f"only {share} %" if share is not None else "unknown"
    return {"claim": sentence, "verdict": "pruefen",
            "reason": f"\"Proteinreich\" braucht mindestens 20 % der Energie aus Eiweiß, hier {known}.",
            "reason_en": f"\"High protein\" needs at least 20 % of the energy from protein, here {known_en}.",
            "rule": R_NUTRITION[0], "rule_en": R_NUTRITION[1],
            "suggestion": "Quelle von Eiweiß, falls mindestens 12 % der Energie aus Eiweiß stammen.",
            "suggestion_en": "Source of protein, if at least 12 % of the energy comes from protein."}


def user_prompt(sentences: list[str]) -> str:
    return "Sätze:\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(sentences, 1))


# ---- Antwort lesen und Funde bauen -----------------------------------------------------------

def parse_verdicts(raw: str, n: int) -> list[dict]:
    """JSON der Modellantwort lesen. Gibt gueltige Urteile mit idx (0 basiert) zurueck."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            raise LLMError("Antwort ist kein JSON")
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError as exc:
            raise LLMError("Antwort ist kein JSON") from exc
    items = data.get("verdicts") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise LLMError("Feld verdicts fehlt")
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            idx = int(it.get("id")) - 1
        except (TypeError, ValueError):
            continue
        verdict = str(it.get("verdict", "")).strip().lower()
        if not 0 <= idx < n or verdict not in VERDICTS:
            continue
        g = lambda k: str(it.get(k) or "").strip()  # noqa: E731
        rule_id = g("rule_id").upper()
        if verdict == "unzulaessig" and rule_id not in RULES:
            rule_id = "NOT_AUTH"
        out.append({"idx": idx, "verdict": verdict, "rule_id": rule_id if verdict == "unzulaessig" else NO_RULE,
                    "reason": g("reason"), "reason_en": g("reason_en"),
                    "suggestion": g("suggestion"), "suggestion_en": g("suggestion_en")})
    return out


def findings_from_verdicts(sentences: list[str], verdicts: list[dict]) -> list[dict]:
    out, done = [], set()
    for v in verdicts:
        if v["verdict"] != "unzulaessig" or v["idx"] in done:
            continue
        done.add(v["idx"])
        rule_de, rule_en, _ = RULES[v["rule_id"]]
        reason = v["reason"] or rule_de
        suggestion = v["suggestion"]
        out.append({"claim": sentences[v["idx"]], "verdict": "unzulaessig", "reason": reason,
                    "reason_en": v["reason_en"] or reason, "rule": rule_de, "rule_en": rule_en,
                    "suggestion": suggestion, "suggestion_en": v["suggestion_en"] or suggestion})
    return out


# ---- Fake: deterministisch, ohne Netzwerk ----------------------------------------------------

# (Muster, rule_id, Grund DE, Grund EN, Ersatz DE, Ersatz EN). Die Ersatzsaetze loesen den Vorfilter nicht aus.
_MUSCLE = ("Eiweiß trägt zu einer Zunahme an Muskelmasse bei.", "Protein contributes to a growth in muscle mass.")
_FATBURN = ("Enthält Eiweiß, das zum Erhalt der Muskelmasse beiträgt.",
            "Contains protein, which contributes to the maintenance of muscle mass.")
_DISEASE_FIX = ("Dieses Produkt ist ein Nahrungsergänzungsmittel und ersetzt keine ausgewogene Ernährung.",
                "This product is a food supplement and does not replace a balanced diet.")
FAKE_RULES = [
    (r"fatburn\w*|fat[\s-]burn\w*|burns?\s+fat|fettverbrenn\w*|fatburner|verbrenn\w*|körperfett|fettabbau", "NOT_AUTH",
     "Wirkversprechen zur Fettverbrennung ist nicht zugelassen.",
     "A promise of fat burning is not authorised.", *_FATBURN),
    (r"detox\w*|entgift\w*|metabolism", "NOT_AUTH", "Entgiftungsversprechen ist nicht zugelassen.",
     "A detox promise is not authorised.",
     "Koffein erhöht die Aufmerksamkeit und die Konzentration.",
     "Caffeine increases alertness and concentration."),
    (r"immun\w*|inmun\w*", "NOT_AUTH", "Immunversprechen ist für diese Zutat nicht zugelassen.",
     "An immune claim is not authorised for this ingredient.",
     "Vitamin C trägt zur Verringerung von Müdigkeit und Ermüdung bei.",
     "Vitamin C contributes to the reduction of tiredness and fatigue."),
    (r"heilt|heilend|depression\w*|herzinfarkt|schlaganfall|cholesterin\w*|erkältung\w*|blutdruck|angstzust\w*|krank\w*",
     "DISEASE", "Krankheitsbezogene Aussagen sind für Lebensmittel verboten.",
     "Disease related statements are prohibited for foods.", *_DISEASE_FIX),
    (r"disease\w*|\bcures?\b|\bheals?\b|prevent\w*|cholesterol|cancer|diabetes|depress\w*", "DISEASE",
     "Krankheitsbezogene Aussagen sind für Lebensmittel verboten.",
     "Disease related statements are prohibited for foods.", *_DISEASE_FIX),
    (r"guarante\w*|zehnmal", "MISLEADING", "Garantieversprechen für Wirkungen sind nicht zulässig.",
     "Guarantees of effects are not permitted.", *_MUSCLE),
    (r"muskelaufbau|muskelwachstum|muskeln\s+aufbauen", "NOT_AUTH",
     "Nur die zugelassene Formulierung zur Muskelmasse ist erlaubt.",
     "Only the authorised wording on muscle mass is permitted.", *_MUSCLE),
    (r"abnehm\w*|schlank\w*", "NOT_AUTH", "Gewichtsbezogene Aussagen brauchen eine Zulassung.",
     "Weight related statements need an authorisation.",
     "Enthält pro Portion nur wenige Kalorien.", "Contains only a few calories per serving."),
]


class Checker:
    """Gemeinsame Hilfe: check(p) fuehrt die ganze Pruefung ohne Cache aus."""

    def check(self, p: dict) -> "LLMResult":
        return check_claims(p, self)


class FakeLLM(Checker):
    model = "fake"
    mode = "fake"

    def judge(self, sentences: list[str]) -> Reply:
        verdicts = []
        for i, s in enumerate(sentences):
            for pattern, rule_id, reason, reason_en, sug, sug_en in FAKE_RULES:
                if re.search(pattern, s, re.IGNORECASE):
                    verdicts.append({"idx": i, "verdict": "unzulaessig", "rule_id": rule_id, "reason": reason,
                                     "reason_en": reason_en, "suggestion": sug, "suggestion_en": sug_en})
                    break
            else:
                verdicts.append({"idx": i, "verdict": "zulaessig", "rule_id": NO_RULE, "reason": "",
                                 "reason_en": "", "suggestion": "", "suggestion_en": ""})
        t_in = (len(system_prompt(True)) + len(user_prompt(sentences))) // 4
        return Reply(verdicts, t_in, max(1, len(json.dumps(verdicts)) // 4))


# ---- Ollama ----------------------------------------------------------------------------------

class OllamaLLM(Checker):
    mode = "ollama"

    def __init__(self, model: str | None = None, url: str | None = None, timeout: float = 300) -> None:
        self.model = model or os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)
        self.url = (url or os.environ.get("OLLAMA_URL", DEFAULT_URL)).rstrip("/")
        self.timeout = timeout

    def ping(self) -> None:
        """Vor dem Lauf pruefen, ob Ollama erreichbar ist und das Modell geladen wurde."""
        import httpx
        try:
            tags = httpx.get(f"{self.url}/api/tags", timeout=10).json()
        except Exception as exc:
            raise LLMError(f"Ollama nicht erreichbar unter {self.url}: {exc}") from exc
        names = {m.get("name") for m in tags.get("models", [])}
        if self.model not in names and f"{self.model}:latest" not in names:
            raise LLMError(f"Modell {self.model} fehlt. Mit `ollama pull {self.model}` laden.")

    def judge(self, sentences: list[str]) -> Reply:
        import httpx
        body = {
            "model": self.model, "stream": False, "format": "json",
            "options": {"temperature": 0},
            "messages": [{"role": "system", "content": system_prompt(english=False)},
                         {"role": "user", "content": user_prompt(sentences)}],
        }
        start = time.monotonic()
        try:
            r = httpx.post(f"{self.url}/api/chat", json=body, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            raise LLMError(f"Ollama Anfrage fehlgeschlagen: {exc}") from exc
        seconds = round(time.monotonic() - start, 2)
        verdicts = parse_verdicts(data.get("message", {}).get("content", ""), len(sentences))
        return Reply(verdicts, data.get("prompt_eval_count", 0), data.get("eval_count", 0), seconds)


# ---- Claude ----------------------------------------------------------------------------------

def cost_usd(tokens_in: int, tokens_out: int, cache_write: int = 0, cache_read: int = 0) -> float:
    return (tokens_in * PRICE_IN + tokens_out * PRICE_OUT + cache_write * PRICE_IN * CACHE_WRITE_FACTOR
            + cache_read * PRICE_IN * CACHE_READ_FACTOR) / 1_000_000


class ClaudeLLM(Checker):
    """Claude Haiku ueber das offizielle anthropic SDK. Key nur aus ANTHROPIC_API_KEY."""
    mode = "claude"

    def __init__(self, model: str | None = None, client=None, budget_usd: float = BUDGET_USD) -> None:
        self.model = model or os.environ.get("CLAUDE_MODEL", DEFAULT_CLAUDE_MODEL)
        self.budget_usd = budget_usd
        self.spent_usd = 0.0
        if client is None:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise LLMError("LLM_MODE=claude braucht die Umgebungsvariable ANTHROPIC_API_KEY")
            try:
                import anthropic
            except ImportError as exc:
                raise LLMError('anthropic fehlt: pip install -e ".[anthropic]"') from exc
            client = anthropic.Anthropic()  # liest ANTHROPIC_API_KEY selbst
        self.client = client
        self.system = system_prompt(english=True)

    def estimate_usd(self, sentences: list[str], max_tokens: int) -> float:
        """Obergrenze vor dem Aufruf: Eingabe grob (3 Zeichen je Token) plus volle Ausgabe."""
        est_in = (len(self.system) + len(user_prompt(sentences))) // 3 + 1
        return cost_usd(est_in, max_tokens)

    def judge(self, sentences: list[str]) -> Reply:
        max_tokens = min(4096, 300 + 250 * len(sentences))
        worst = self.estimate_usd(sentences, max_tokens)
        if self.spent_usd + worst > self.budget_usd:
            raise BudgetExceeded(
                f"Budget {self.budget_usd:.2f} USD wuerde ueberschritten "
                f"(bisher {self.spent_usd:.4f} USD, naechster Aufruf bis {worst:.4f} USD)")
        start = time.monotonic()
        try:
            resp = self.client.messages.create(
                model=self.model, max_tokens=max_tokens,
                system=[{"type": "text", "text": self.system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user_prompt(sentences)}],
                thinking={"type": "disabled"},
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": verdict_schema()}},
            )
        except Exception as exc:
            raise LLMError(f"Claude Anfrage fehlgeschlagen: {exc}") from exc
        seconds = round(time.monotonic() - start, 2)
        u = resp.usage
        t_in, t_out = u.input_tokens, u.output_tokens
        c_write = getattr(u, "cache_creation_input_tokens", 0) or 0
        c_read = getattr(u, "cache_read_input_tokens", 0) or 0
        cost = cost_usd(t_in, t_out, c_write, c_read)
        self.spent_usd += cost  # auch bei kaputter Antwort, der Aufruf wurde berechnet
        if getattr(resp, "stop_reason", "") == "max_tokens":
            raise LLMError("Antwort abgeschnitten (max_tokens)")
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        verdicts = parse_verdicts(text, len(sentences))
        return Reply(verdicts, t_in + c_write + c_read, t_out, seconds, cost)


def get_llm(mode: str | None = None):
    mode = (mode or os.environ.get("LLM_MODE", "fake")).lower()
    if mode == "fake":
        return FakeLLM()
    if mode == "ollama":
        return OllamaLLM()
    if mode == "claude":
        return ClaudeLLM()
    raise ValueError(f"unbekannter LLM_MODE: {mode}")


# ---- Cache und Ablauf ------------------------------------------------------------------------

def cache_key(model: str, text: str) -> str:
    raw = f"{PROMPT_VERSION}|{model}|{text}"
    return hashlib.sha256(raw.encode()).hexdigest()


class ResultCache:
    """Kleiner JSON Cache auf Platte, Schluessel ist der Hash der verdaechtigen Saetze."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self.data: dict[str, dict] = {}
        if self.path and self.path.exists():
            self.data = json.loads(self.path.read_text())

    def get(self, key: str) -> dict | None:
        return self.data.get(key)

    def set(self, key: str, value: dict) -> None:
        self.data[key] = value
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, ensure_ascii=False))


def check_claims(p: dict, llm, cache: ResultCache | None = None) -> LLMResult:
    """Claims eines Produkts pruefen: Vorfilter, ein Modellaufruf fuer verdaechtige Saetze, Cache."""
    if not product_text(p):
        return LLMResult([], llm.model, llm.mode)
    pre = prefilter(p)
    res = LLMResult(list(pre.local_findings), llm.model, llm.mode,
                    allowed=len(pre.allowed), suspicious=len(pre.suspicious))
    if not pre.suspicious:
        return res
    key = cache_key(llm.model, "\n".join(pre.suspicious))
    hit = cache.get(key) if cache else None
    if hit:
        verdicts = hit["verdicts"]
        res.tokens_in, res.tokens_out, res.seconds, res.cached = hit["tokens_in"], hit["tokens_out"], hit["seconds"], True
    else:
        try:
            reply = llm.judge(pre.suspicious)
        except BudgetExceeded:
            raise
        except LLMError:  # ein zweiter Versuch, kleine Modelle liefern manchmal kaputtes JSON
            try:
                reply = llm.judge(pre.suspicious)
            except BudgetExceeded:
                raise
            except LLMError as exc:
                res.error = str(exc)
                return res
        verdicts = reply.verdicts
        res.tokens_in, res.tokens_out, res.seconds, res.cost_usd = (
            reply.tokens_in, reply.tokens_out, reply.seconds, reply.cost_usd)
        if cache is not None:
            cache.set(key, {"verdicts": verdicts, "tokens_in": reply.tokens_in, "tokens_out": reply.tokens_out,
                            "seconds": reply.seconds, "cost_usd": reply.cost_usd})
    res.findings += findings_from_verdicts(pre.suspicious, verdicts)
    return res
