import json

import pytest

from labellab import llm as L
from types import SimpleNamespace

from labellab.llm import (BudgetExceeded, ClaudeLLM, FakeLLM, LLMError, ResultCache, check_claims, parse_verdicts,
                          prefilter)
from labellab.pipeline import check_product


def product(name="Whey Protein", **kw):
    p = {"code": "1", "name": name, "generic_name": "", "labels": "", "ingredients": "Molkenprotein",
         "serving_size": "30 g", "allergens_tags": ["en:milk"],
         "nutriments": {"energy-kcal_100g": 400, "fat_100g": 5, "carbohydrates_100g": 20,
                        "sugars_100g": 5, "proteins_100g": 68, "salt_100g": 0.5}}
    p.update(kw)
    return p


def test_fake_is_default_in_tests():
    assert L.get_llm().mode == "fake"


def test_fake_finds_unauthorized_claim_with_suggestion_and_rule():
    res = FakeLLM().check(product("Shake", description="Der Shake entgiftet den Körper."))
    assert len(res.findings) == 1 and res.findings[0]["claim"] == "Der Shake entgiftet den Körper."
    for f in res.findings:
        for key in ("reason", "reason_en", "rule", "rule_en", "suggestion", "suggestion_en"):
            assert f[key], key
        assert "Art." in f["rule"] and "Art." in f["rule_en"]


def test_fake_suggestions_do_not_trigger_the_prefilter():
    """Grundlage fuer den Uebernehmen Button: der Vorschlag selbst ist unauffaellig."""
    for *_, sug, sug_en in L.FAKE_RULES:
        for text in (sug, sug_en):
            assert FakeLLM().check(product("Shake", description=text)).findings == []


def test_every_fake_pattern_is_reachable_through_the_suspicious_filter():
    for pattern, *_ in L.FAKE_RULES:
        word = pattern.split("|")[0].replace("\\w*", "").replace("\\s?", "").replace("\\s+", " ")
        assert L.SUSPICIOUS_RE.search(word), word


def test_prompt_version_and_rule_ids_in_prompt():
    assert L.PROMPT_VERSION == "3"
    for rid in L.RULES:
        assert rid in L.system_prompt(False)
    assert "reason_en" in L.system_prompt(True) and "reason_en" not in L.system_prompt(False)


def test_legal_bases_are_correct():
    assert L.RULES["DISEASE"][0].startswith("Art. 7 Abs. 3 VO (EU) 1169/2011")
    assert L.RULES["NOT_AUTH"][0].startswith("Art. 10 Abs. 1 VO (EG) 1924/2006")
    assert L.RULES["WEIGHT_RATE"][0].startswith("Art. 12 Buchst. b VO (EG) 1924/2006")
    assert L.RULES["DOCTOR"][0].startswith("Art. 12 Buchst. c VO (EG) 1924/2006")
    for de, en, _ in L.RULES.values():
        assert de and en and "Art." in en


# ---- Vorfilter und Allowlist -----------------------------------------------------------------

def test_allowlist_sentences_are_not_sent_to_the_model():
    for s in ("Protein trägt zu einer Zunahme an Muskelmasse bei.", "Eiweiß trägt zum Erhalt von Muskelmasse bei.",
              "Zink trägt zu einer normalen Funktion des Immunsystems bei.",
              "Vitamin C trägt zur Verringerung von Müdigkeit und Ermüdung bei.",
              "Magnesium trägt zu einer normalen Muskelfunktion bei und zur Verringerung von Müdigkeit und Ermüdung.",
              "Vitamin B12 trägt zu einem normalen Energiestoffwechsel bei.",
              "Kreatin erhöht die körperliche Leistung bei kurzzeitigen, intensiven Belastungen, wenn du täglich 3 g einnimmst.",
              "DHA trägt zur Erhaltung einer normalen Gehirnfunktion bei."):
        pre = prefilter(product("Shake", description=s))
        assert pre.allowed == [s] and pre.suspicious == [], s


def test_allowed_claim_with_extra_promise_still_goes_to_the_model():
    s = "Zink trägt zu einer normalen Funktion des Immunsystems bei und heilt Erkältungen."
    assert prefilter(product("Shake", description=s)).suspicious == [s]


def test_caffeine_is_not_on_the_allowlist():
    s = "Koffein trägt zu einer normalen Funktion des Immunsystems bei."
    assert prefilter(product("Shake", description=s)).allowed == []


def test_only_suspicious_sentences_are_sent_and_neutral_ones_are_dropped():
    desc = ("Eine Portion in 300 ml Wasser shaken. Das Protein beschleunigt deine Fettverbrennung. "
            "Protein trägt zu einer Zunahme an Muskelmasse bei. Garantiert sichtbare Ergebnisse in zwei Wochen!")
    pre = prefilter(product("Shake", description=desc))
    assert pre.suspicious == ["Das Protein beschleunigt deine Fettverbrennung.",
                              "Garantiert sichtbare Ergebnisse in zwei Wochen!"]
    assert pre.allowed == ["Protein trägt zu einer Zunahme an Muskelmasse bei."]


def test_suspicious_keywords():
    for word in ("verbrennt Fett", "heilt", "Immunsystem", "garantiert", "Ergebnisse", "schützt", "Detox",
                 "Stoffwechsel", "Krankheit", "Herzinfarkt", "abnehmen"):
        assert L.SUSPICIOUS_RE.search(f"Das Produkt {word} sofort."), word
    assert not L.SUSPICIOUS_RE.search("Eine Portion in 300 ml Wasser shaken.")


def test_sentences_are_literal_substrings_of_the_text():
    p = product("Shake", description="Erster Satz. Zweiter Satz! Dritter?\nVierter Satz.")
    text = L.product_text(p)
    assert all(s in text for s in L.split_sentences(text)) and len(L.split_sentences(text)) == 5


def test_proteinreich_is_checked_in_python_without_the_model():
    llm = CountingLLM()
    ok = check_claims(product("Proteinreich Pulver"), llm)           # 68 g -> 68 % der Energie
    low = check_claims(product("Proteinreich Müsli", nutriments={"energy-kcal_100g": 400, "proteins_100g": 10}), llm)
    assert ok.findings == [] and low.findings[0]["verdict"] == "pruefen" and llm.calls == 0
    assert low.findings[0]["rule"].startswith("Art. 8 Abs. 1")


def test_clean_text_no_findings_and_no_call():
    llm = CountingLLM()
    assert check_claims(product("Whey Protein Vanille"), llm).findings == [] and llm.calls == 0


def test_fake_is_deterministic():
    p = product("Muskelaufbau Shake")
    assert FakeLLM().check(p).findings == FakeLLM().check(p).findings


# ---- Antwort lesen ---------------------------------------------------------------------------

def test_parse_verdicts_valid_and_filters():
    raw = json.dumps({"verdicts": [
        {"id": 1, "verdict": "unzulaessig", "rule_id": "DISEASE", "reason": "r", "suggestion": "e"},
        {"id": 2, "verdict": "zulaessig", "rule_id": "KEINE", "reason": "", "suggestion": ""},
        {"id": 3, "verdict": "unzulaessig", "rule_id": "ERFUNDEN", "reason": "x"},
        {"id": 9, "verdict": "unzulaessig", "rule_id": "DISEASE"}, {"id": "x", "verdict": "pruefen"}]})
    out = parse_verdicts(raw, 3)
    assert [v["idx"] for v in out] == [0, 1, 2]
    assert out[0]["rule_id"] == "DISEASE" and out[2]["rule_id"] == "NOT_AUTH"  # unbekannte ID faellt zurueck


def test_findings_use_rule_text_from_code_and_fall_back_to_german():
    sents = ["Heilt Depressionen."]
    v = parse_verdicts(json.dumps({"verdicts": [{"id": 1, "verdict": "unzulaessig", "rule_id": "DISEASE",
                                                 "reason": "Krankheitsbezug.", "suggestion": "Ersatz."}]}), 1)
    f = L.findings_from_verdicts(sents, v)[0]
    assert f["rule"] == L.RULES["DISEASE"][0] and f["rule_en"] == L.RULES["DISEASE"][1]
    assert f["reason_en"] == "Krankheitsbezug." and f["suggestion_en"] == "Ersatz."  # Rueckfall auf Deutsch
    assert f["claim"] == "Heilt Depressionen."


def test_parse_verdicts_extracts_json_from_noise():
    assert parse_verdicts('Hier: {"verdicts": []} Ende', 1) == []


def test_parse_verdicts_rejects_garbage():
    with pytest.raises(LLMError):
        parse_verdicts("kein json", 1)
    with pytest.raises(LLMError):
        parse_verdicts('{"foo": 1}', 1)


# ---- Cache und Aufrufe -----------------------------------------------------------------------

class CountingLLM(FakeLLM):
    def __init__(self):
        self.calls = 0

    def judge(self, sentences):
        self.calls += 1
        return super().judge(sentences)


def test_one_model_call_per_product_for_all_suspicious_sentences():
    llm = CountingLLM()
    desc = "Das entgiftet. Das heilt Erkältungen. Das verbrennt Fett."
    res = check_claims(product("Shake", description=desc), llm)
    assert llm.calls == 1 and len(res.findings) == 3 and res.suspicious == 3


def test_cache_avoids_second_call(tmp_path):
    cache, llm = ResultCache(tmp_path / "c.json"), CountingLLM()
    p = product("Fatburner Shake", description="Das Pulver entgiftet.")
    first = check_claims(p, llm, cache)
    second = check_claims(p, llm, cache)
    assert llm.calls == 1 and not first.cached and second.cached
    assert second.findings == first.findings and second.cost_usd == 0


def test_cache_persists_on_disk(tmp_path):
    path = tmp_path / "c.json"
    p = product("Shake", description="Das Pulver entgiftet.")
    check_claims(p, CountingLLM(), ResultCache(path))
    llm = CountingLLM()
    assert check_claims(p, llm, ResultCache(path)).cached and llm.calls == 0


def test_cache_key_depends_on_text_and_model():
    assert L.cache_key("a", "x") != L.cache_key("a", "y") != L.cache_key("b", "y")


def test_empty_text_makes_no_call():
    llm = CountingLLM()
    res = check_claims(product(name="", generic_name="", labels=""), llm, None)
    assert llm.calls == 0 and res.findings == []


def test_failing_llm_retries_once_then_reports_error(tmp_path):
    class Broken(FakeLLM):
        calls = 0

        def judge(self, sentences):
            Broken.calls += 1
            raise LLMError("kaputt")

    cache = ResultCache(tmp_path / "c.json")
    res = check_claims(product("Shake", description="Das Pulver entgiftet."), Broken(), cache)
    assert Broken.calls == 2 and res.error == "kaputt" and cache.data == {}


def test_usage_is_recorded():
    res = FakeLLM().check(product("Fatburner", description="Das verbrennt Fett."))
    assert res.tokens_in > 0 and res.tokens_out > 0 and res.seconds == 0.0 and res.cost_usd == 0


# ---- Ollama ----------------------------------------------------------------------------------

def test_ollama_request_and_usage(monkeypatch):
    sent = {}

    class Resp:
        def raise_for_status(self): pass

        def json(self):
            return {"message": {"content": '{"verdicts": [{"id": 1, "verdict": "unzulaessig", "rule_id": "NOT_AUTH",'
                                           ' "reason": "r", "suggestion": "e"}]}'},
                    "prompt_eval_count": 321, "eval_count": 45}

    import httpx
    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: sent.update(url=url, body=json) or Resp())
    res = L.OllamaLLM(model="qwen2.5:3b", url="http://x:11434").check(
        product("Shake", description="Das Pulver entgiftet."))
    assert sent["url"] == "http://x:11434/api/chat" and sent["body"]["format"] == "json"
    assert sent["body"]["model"] == "qwen2.5:3b" and sent["body"]["stream"] is False
    assert "1. Das Pulver entgiftet." in sent["body"]["messages"][1]["content"]
    assert (res.tokens_in, res.tokens_out) == (321, 45) and res.seconds >= 0 and res.cost_usd == 0
    assert res.findings[0]["claim"] == "Das Pulver entgiftet." and res.findings[0]["reason_en"] == "r"


def test_ollama_model_from_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1:8b")
    assert L.OllamaLLM().model == "llama3.1:8b"
    monkeypatch.delenv("OLLAMA_MODEL")
    assert L.OllamaLLM().model == "qwen2.5:3b"


def test_ollama_unreachable_gives_llm_error():
    with pytest.raises(LLMError):
        L.OllamaLLM(url="http://127.0.0.1:9").ping()


def test_unknown_mode():
    with pytest.raises(ValueError):
        L.get_llm("gpt")


# ---- Claude (gemockter Client, kein Netzwerk) ------------------------------------------------

class FakeClient:
    """Ersetzt anthropic.Anthropic: liefert feste Urteile und feste Token Zahlen."""

    def __init__(self, tokens_in=1000, tokens_out=200, cache_write=0, cache_read=0):
        self.calls, self.usage = [], SimpleNamespace(
            input_tokens=tokens_in, output_tokens=tokens_out,
            cache_creation_input_tokens=cache_write, cache_read_input_tokens=cache_read)
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        n = kw["messages"][0]["content"].count("\n")
        verdicts = [{"id": i, "verdict": "unzulaessig", "rule_id": "NOT_AUTH", "reason": "Grund.",
                     "reason_en": "Reason.", "suggestion": "Ersatz.", "suggestion_en": "Fix."}
                    for i in range(1, n + 1)]
        block = SimpleNamespace(type="text", text=json.dumps({"verdicts": verdicts}))
        return SimpleNamespace(content=[block], usage=self.usage, stop_reason="end_turn")


def claude(**kw):
    return ClaudeLLM(client=kw.pop("client", None) or FakeClient(), **kw)


def test_claude_request_shape_and_findings():
    llm = claude()
    res = llm.check(product("Shake", description="Das Pulver entgiftet."))
    req = llm.client.calls[0]
    assert req["model"] == "claude-haiku-5-5" and req["system"][0]["cache_control"] == {"type": "ephemeral"}
    fmt = req["output_config"]["format"]
    assert fmt["type"] == "json_schema" and fmt["schema"]["properties"]["verdicts"]
    assert "reason_en" in req["system"][0]["text"]
    assert res.findings[0]["reason_en"] == "Reason." and res.findings[0]["suggestion_en"] == "Fix."
    assert res.mode == "claude" and (res.tokens_in, res.tokens_out) == (1000, 200)


def test_claude_model_from_env_and_key_only_from_environment(monkeypatch):
    monkeypatch.setenv("CLAUDE_MODEL", "claude-sonnet-5-5")
    assert claude().model == "claude-sonnet-5-5"
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        ClaudeLLM()


def test_cost_fields_are_computed_from_usage():
    assert L.cost_usd(1_000_000, 0) == pytest.approx(0.10) and L.cost_usd(0, 1_000_000) == pytest.approx(0.50)
    assert L.cost_usd(0, 0, cache_write=1_000_000) == pytest.approx(0.125)
    assert L.cost_usd(0, 0, cache_read=1_000_000) == pytest.approx(0.01)
    llm = claude(client=FakeClient(1000, 200))
    res = llm.check(product("Shake", description="Das Pulver entgiftet."))
    assert res.cost_usd == pytest.approx(0.0002) and llm.spent_usd == pytest.approx(0.0002)


def test_budget_blocks_call_before_it_is_made():
    llm = claude(budget_usd=0.0001)
    with pytest.raises(BudgetExceeded):
        llm.check(product("Shake", description="Das Pulver entgiftet."))
    assert llm.client.calls == []


def test_budget_stops_run_when_spent_plus_estimate_exceeds_limit(tmp_path):
    cache = ResultCache(tmp_path / "c.json")
    llm = claude(client=FakeClient(tokens_in=1000, tokens_out=400), budget_usd=0.0015)  # 0,0003 USD pro Aufruf
    done = 0
    with pytest.raises(BudgetExceeded):
        for i in range(20):
            check_claims(product("Shake", code=str(i), description=f"Produkt {i} entgiftet."), llm, cache)
            done += 1
    assert 1 <= done < 20 and llm.spent_usd <= 0.0015 and len(llm.client.calls) == done
    assert len(cache.data) == done  # bezahlte Antworten bleiben im Cache, der naechste Lauf macht weiter


def test_budget_default_is_30_cents_and_is_not_swallowed_as_llm_error():
    assert L.BUDGET_USD == 0.30 and claude().budget_usd == 0.30
    assert issubclass(BudgetExceeded, LLMError)
    r = check_product  # Pipeline reicht den Abbruch durch
    with pytest.raises(BudgetExceeded):
        r(product("Shake", description="Das Pulver entgiftet."), claude(budget_usd=0.0))


def test_truncated_answer_is_an_error_but_still_costs():
    client = FakeClient()
    orig = client.create
    client.create = lambda **kw: setattr(orig(**kw), "stop_reason", "max_tokens") or SimpleNamespace(
        content=[], usage=client.usage, stop_reason="max_tokens")
    llm = claude(client=client)
    res = check_claims(product("Shake", description="Das Pulver entgiftet."), llm)
    assert "abgeschnitten" in res.error and llm.spent_usd > 0


def test_pipeline_records_cost_per_product_and_total(tmp_path):
    from labellab.pipeline import export_results, run_all
    llm = claude()
    prods = [product("A", code="1", description="Das entgiftet."), product("B", code="2"),
             product("C", code="3", description="Das heilt Erkältungen.")]
    results = run_all(prods, llm)
    meta = export_results(results, llm, tmp_path / "r.json")
    costs = [r["llm"]["cost_usd"] for r in results]
    assert costs == [pytest.approx(0.0002), 0, pytest.approx(0.0002)]
    assert meta["api_cost_usd"] == pytest.approx(0.0004, abs=1e-4) and meta["budget_usd"] == 0.30
    assert meta["mode"] == "claude" and meta["claims_to_model"] == 2
    assert json.loads((tmp_path / "r.json").read_text())["meta"]["api_cost_usd"] == meta["api_cost_usd"]


def test_pipeline_status_and_llm_fields(tmp_path):
    r = check_product(product("Shake", description="Das verbrennt Fett.", source="brand"), FakeLLM(),
                      ResultCache(tmp_path / "c.json"))
    assert r["status"] == "red" and r["checks"]["claims"] == "red"
    assert r["llm"]["mode"] == "fake" and "seconds" in r["llm"] and r["llm"]["cost_usd"] == 0
    assert r["llm"]["suspicious"] == 1
    clean = check_product(product(), FakeLLM())
    assert clean["status"] == "green"
