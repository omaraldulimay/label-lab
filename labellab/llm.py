"""Claim-Pruefung mit lokalem Modell (Ollama) oder deterministischem Fake.

Nur hier kommt ein Sprachmodell zum Einsatz. Es laeuft lokal ueber die Ollama HTTP API,
es gibt keinen API Key und keine laufenden Kosten. Ergebnisse werden per Hash des
Produkttexts gecacht, damit nichts doppelt gerechnet wird.
"""
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

PROMPT_VERSION = "1"
DEFAULT_MODEL = "qwen2.5:3b"
DEFAULT_URL = "http://localhost:11434"
VERDICTS = {"unzulaessig", "pruefen"}

SYSTEM_PROMPT = """Du prüfst Werbeaussagen auf Lebensmitteln (Supplements, Proteinprodukte) nach der \
EU-Verordnung 1924/2006 (Health-Claims-Verordnung).

Regeln:
- Nährwertbezogene Angaben sind nur erlaubt, wenn die Bedingungen im Anhang erfüllt sind. \
"Proteinreich" braucht mindestens 20 % der Energie aus Eiweiß, "Quelle von Eiweiß" mindestens 12 %. \
"Zuckerfrei" braucht höchstens 0,5 g Zucker pro 100 g.
- Gesundheitsbezogene Angaben sind nur erlaubt, wenn sie im EU-Register zugelassen sind, zum Beispiel \
"Eiweiß trägt zum Erhalt von Muskelmasse bei" und "Eiweiß trägt zu einer Zunahme an Muskelmasse bei" \
(Voraussetzung: Quelle von Eiweiß).
- Unzulässig sind Aussagen, die Krankheiten heilen oder verhindern, und nicht zugelassene Wirkversprechen \
wie "Fatburner", "entgiftet", "stärkt das Immunsystem", "beschleunigt die Fettverbrennung", \
"garantiert Muskelaufbau".
- Ein Nährwert oder eine Zahl ohne Werbeaussage ist kein Fund.

Antworte nur mit JSON in diesem Format:
{"findings": [{"claim": "wörtliche Aussage aus dem Text", "verdict": "unzulaessig" oder "pruefen", \
"reason": "ein kurzer Satz", "replacement": "zulässiger Ersatztext in einem Satz"}]}
Gibt es keine problematische Aussage, antworte {"findings": []}. Erfinde keine Aussagen, die nicht im Text stehen."""


class LLMError(RuntimeError):
    pass


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


def build_user_prompt(p: dict) -> str:
    share = protein_share(p)
    facts = f"Eiweißanteil an der Energie: {share} %" if share is not None else "Eiweißanteil unbekannt"
    return f"Produkttext:\n{product_text(p)}\n\n{facts}"


def cache_key(model: str, text: str) -> str:
    raw = f"{PROMPT_VERSION}|{model}|{text}"
    return hashlib.sha256(raw.encode()).hexdigest()


class ResultCache:
    """Kleiner JSON Cache auf Platte, Schluessel ist der Hash des Produkttexts."""

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


def parse_findings(raw: str) -> list[dict]:
    """JSON aus der Modellantwort lesen und auf gueltige Funde reduzieren."""
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
    items = data.get("findings") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise LLMError("Feld findings fehlt")
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        claim, verdict = str(it.get("claim", "")).strip(), str(it.get("verdict", "")).strip().lower()
        if not claim or verdict not in VERDICTS:
            continue
        out.append({"claim": claim, "verdict": verdict,
                    "reason": str(it.get("reason", "")).strip(),
                    "replacement": str(it.get("replacement", "")).strip()})
    return out


# ---- Fake: deterministisch, ohne Netzwerk ----------------------------------------------------

FAKE_RULES = [  # (Muster, Urteil, Grund, Ersatz)
    (r"fat\s?burn\w*|fettverbrenn\w*|fatburner", "unzulaessig",
     "Wirkversprechen zur Fettverbrennung ist nicht zugelassen.",
     "Enthält Eiweiß, das zum Erhalt der Muskelmasse beiträgt."),
    (r"detox\w*|entgift\w*", "unzulaessig", "Entgiftungsversprechen ist nicht zugelassen.",
     "Ohne Entgiftungsaussage vermarkten, nur den Nährwert nennen."),
    (r"immun\w*", "unzulaessig", "Immunversprechen ist für Eiweiß nicht zugelassen.",
     "Für Vitamin C: Vitamin C trägt zu einer normalen Funktion des Immunsystems bei."),
    (r"heilt|heilend", "unzulaessig", "Krankheitsbezogene Aussagen sind verboten.",
     "Aussage streichen, Lebensmittel dürfen keine Krankheiten heilen."),
    (r"garantiert\w*", "unzulaessig", "Garantieversprechen für Wirkungen sind nicht zulässig.",
     "Eiweiß trägt zu einer Zunahme an Muskelmasse bei."),
    (r"muskelaufbau|muskelwachstum|muskeln\s+aufbauen", "pruefen",
     "Nur die zugelassene Formulierung zur Muskelmasse ist erlaubt.",
     "Eiweiß trägt zu einer Zunahme an Muskelmasse bei."),
    (r"abnehm\w*|schlank\w*", "pruefen", "Gewichtsbezogene Aussagen brauchen eine Zulassung.",
     "Ohne Gewichtsversprechen, zum Beispiel nur den Kaloriengehalt nennen."),
    (r"proteinreich|high\s?protein|eiweißreich|eiweissreich", "pruefen",
     "Erlaubt nur, wenn mindestens 20 % der Energie aus Eiweiß stammen.",
     "Quelle von Eiweiß, falls mindestens 12 % der Energie aus Eiweiß stammen."),
]


class FakeLLM:
    model = "fake"
    mode = "fake"

    def check(self, p: dict) -> LLMResult:
        text = product_text(p)
        findings = []
        share = protein_share(p)
        for pattern, verdict, reason, repl in FAKE_RULES:
            m = re.search(pattern, text, re.IGNORECASE)
            if not m:
                continue
            if "proteinreich" in pattern and share is not None and share >= 20:
                continue  # Bedingung erfuellt, kein Fund
            findings.append({"claim": m.group(0), "verdict": verdict, "reason": reason, "replacement": repl})
        t_in = (len(SYSTEM_PROMPT) + len(build_user_prompt(p))) // 4
        t_out = max(1, len(json.dumps(findings)) // 4)
        return LLMResult(findings, self.model, self.mode, t_in, t_out, 0.0)


# ---- Ollama ----------------------------------------------------------------------------------

class OllamaLLM:
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

    def check(self, p: dict) -> LLMResult:
        import httpx
        body = {
            "model": self.model, "stream": False, "format": "json",
            "options": {"temperature": 0},
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": build_user_prompt(p)}],
        }
        start = time.monotonic()
        try:
            r = httpx.post(f"{self.url}/api/chat", json=body, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            raise LLMError(f"Ollama Anfrage fehlgeschlagen: {exc}") from exc
        seconds = round(time.monotonic() - start, 2)
        findings = parse_findings(data.get("message", {}).get("content", ""))
        return LLMResult(findings, self.model, self.mode, data.get("prompt_eval_count", 0),
                         data.get("eval_count", 0), seconds)


def get_llm(mode: str | None = None):
    mode = (mode or os.environ.get("LLM_MODE", "fake")).lower()
    if mode == "fake":
        return FakeLLM()
    if mode == "ollama":
        return OllamaLLM()
    raise ValueError(f"unbekannter LLM_MODE: {mode}")


def check_claims(p: dict, llm, cache: ResultCache | None = None) -> LLMResult:
    """Claims eines Produkts pruefen, mit Cache. Ohne Text gibt es nichts zu pruefen."""
    if not product_text(p):
        return LLMResult([], llm.model, llm.mode)
    key = cache_key(llm.model, build_user_prompt(p))
    hit = cache.get(key) if cache else None
    if hit:
        return LLMResult(hit["findings"], llm.model, llm.mode, hit["tokens_in"], hit["tokens_out"],
                         hit["seconds"], cached=True)
    try:
        res = llm.check(p)
    except LLMError:  # ein zweiter Versuch, kleine Modelle liefern manchmal kaputtes JSON
        try:
            res = llm.check(p)
        except LLMError as exc:
            return LLMResult([], llm.model, llm.mode, error=str(exc))
    if cache is not None:
        cache.set(key, {"findings": res.findings, "tokens_in": res.tokens_in,
                        "tokens_out": res.tokens_out, "seconds": res.seconds})
    return res
