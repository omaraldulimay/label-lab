import json

import pytest

from labellab import llm as L
from labellab.llm import FakeLLM, LLMError, LLMResult, ResultCache, check_claims, parse_findings
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


def test_fake_finds_unauthorized_claim_with_replacement():
    res = FakeLLM().check(product("Fatburner Shake", generic_name="entgiftet den Körper"))
    verdicts = {f["claim"].lower(): f["verdict"] for f in res.findings}
    assert verdicts["fatburner"] == "unzulaessig" and "entgiftet" in verdicts
    assert all(f["replacement"] for f in res.findings)


def test_fake_is_deterministic():
    p = product("Muskelaufbau Shake")
    assert FakeLLM().check(p).findings == FakeLLM().check(p).findings


def test_proteinreich_ok_when_share_high():
    assert FakeLLM().check(product("Proteinreich Pulver")).findings == []  # 68 g -> 68 % der Energie


def test_proteinreich_flagged_when_share_low():
    p = product("Proteinreich Müsli", nutriments={"energy-kcal_100g": 400, "proteins_100g": 10})
    assert FakeLLM().check(p).findings[0]["verdict"] == "pruefen"


def test_clean_text_no_findings():
    assert FakeLLM().check(product("Whey Protein Vanille")).findings == []


def test_parse_findings_valid_and_filters():
    raw = json.dumps({"findings": [
        {"claim": "Fatburner", "verdict": "unzulaessig", "reason": "r", "replacement": "e"},
        {"claim": "ok", "verdict": "zulaessig", "reason": "", "replacement": ""},
        {"claim": "", "verdict": "pruefen"}]})
    out = parse_findings(raw)
    assert len(out) == 1 and out[0]["claim"] == "Fatburner"


def test_parse_findings_extracts_json_from_noise():
    assert parse_findings('Hier: {"findings": []} Ende') == []


def test_parse_findings_rejects_garbage():
    with pytest.raises(LLMError):
        parse_findings("kein json")
    with pytest.raises(LLMError):
        parse_findings('{"foo": 1}')


class CountingLLM(FakeLLM):
    def __init__(self):
        self.calls = 0

    def check(self, p):
        self.calls += 1
        return super().check(p)


def test_cache_avoids_second_call(tmp_path):
    cache, llm = ResultCache(tmp_path / "c.json"), CountingLLM()
    p = product("Fatburner Shake")
    first = check_claims(p, llm, cache)
    second = check_claims(p, llm, cache)
    assert llm.calls == 1 and not first.cached and second.cached
    assert second.findings == first.findings


def test_cache_persists_on_disk(tmp_path):
    path = tmp_path / "c.json"
    check_claims(product("Fatburner"), CountingLLM(), ResultCache(path))
    llm = CountingLLM()
    assert check_claims(product("Fatburner"), llm, ResultCache(path)).cached and llm.calls == 0


def test_cache_key_depends_on_text_and_model():
    assert L.cache_key("a", "x") != L.cache_key("a", "y") != L.cache_key("b", "y")


def test_empty_text_makes_no_call():
    llm = CountingLLM()
    res = check_claims(product(name="", generic_name="", labels=""), llm, None)
    assert llm.calls == 0 and res.findings == []


def test_failing_llm_retries_once_then_reports_error(tmp_path):
    class Broken(FakeLLM):
        calls = 0

        def check(self, p):
            Broken.calls += 1
            raise LLMError("kaputt")

    cache = ResultCache(tmp_path / "c.json")
    res = check_claims(product(), Broken(), cache)
    assert Broken.calls == 2 and res.error == "kaputt" and cache.data == {}


def test_usage_is_recorded():
    res = FakeLLM().check(product("Fatburner"))
    assert res.tokens_in > 0 and res.tokens_out > 0 and res.seconds == 0.0


def test_ollama_request_and_usage(monkeypatch):
    sent = {}

    class Resp:
        def raise_for_status(self): pass

        def json(self):
            return {"message": {"content": '{"findings": [{"claim": "Fatburner", "verdict": "unzulaessig",'
                                           ' "reason": "r", "replacement": "e"}]}'},
                    "prompt_eval_count": 321, "eval_count": 45}

    import httpx
    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: sent.update(url=url, body=json) or Resp())
    res = L.OllamaLLM(model="qwen2.5:7b", url="http://x:11434").check(product("Fatburner"))
    assert sent["url"] == "http://x:11434/api/chat" and sent["body"]["format"] == "json"
    assert sent["body"]["model"] == "qwen2.5:7b" and sent["body"]["stream"] is False
    assert (res.tokens_in, res.tokens_out) == (321, 45) and res.seconds >= 0
    assert res.findings[0]["claim"] == "Fatburner"


def test_ollama_model_from_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1:8b")
    assert L.OllamaLLM().model == "llama3.1:8b"
    monkeypatch.delenv("OLLAMA_MODEL")
    assert L.OllamaLLM().model == "qwen2.5:7b"


def test_ollama_unreachable_gives_llm_error():
    with pytest.raises(LLMError):
        L.OllamaLLM(url="http://127.0.0.1:9").ping()


def test_unknown_mode():
    with pytest.raises(ValueError):
        L.get_llm("gpt")


def test_pipeline_status_and_llm_fields(tmp_path):
    r = check_product(product("Fatburner Shake"), FakeLLM(), ResultCache(tmp_path / "c.json"))
    assert r["status"] == "red" and r["checks"]["claims"] == "red"
    assert r["llm"]["mode"] == "fake" and "seconds" in r["llm"] and "tokens_in" in r["llm"]
    clean = check_product(product(), FakeLLM())
    assert clean["status"] == "green"
