"""Nährwertangaben prüft nur Python, das Modell sieht sie nie."""
from labellab.llm import check_claims, prefilter
from labellab.nutrition import check_nutrition, nutrition_finding
from labellab.pipeline import check_product, rescore, write_results, read_results

from test_llm import product


class NoCallLLM:
    model, mode = "none", "claude"

    def judge(self, sentences):
        raise AssertionError("Modell darf nicht aufgerufen werden: " + repr(sentences))


LOW = {"energy-kcal_100g": 408, "proteins_100g": 19, "fat_100g": 10, "sugars_100g": 46}  # 18,6 % Energie aus Eiweiß


def run(p):
    return check_claims(p, NoCallLLM())


def test_high_protein_variants_never_reach_the_model():
    for name, labels in (("LifeBar High Protein Chocolate", ""), ("Bio High Protein Riegel", ""),
                         ("Riegel", "High proteins, No gluten, Vegan"), ("Riegel", "proteinreich")):
        res = run(product(name, labels=labels, nutriments=LOW))
        assert res.suspicious == 0 and [f["verdict"] for f in res.findings] == ["nicht_erfuellt"], (name, labels)


def test_high_protein_fulfilled_is_allowed():
    res = run(product("High Protein Riegel"))  # 68 g Eiweiß, 68 % der Energie
    assert res.findings == [] and res.allowed == 1


def test_source_of_protein_needs_12_percent():
    ok = {"energy-kcal_100g": 400, "proteins_100g": 13}
    bad = {"energy-kcal_100g": 400, "proteins_100g": 10}
    assert run(product("Riegel", labels="Source of protein", nutriments=ok)).findings == []
    assert len(run(product("Riegel", labels="Source of protein", nutriments=bad)).findings) == 1


def test_missing_values_are_not_checkable_not_failed():
    res = run(product("High Protein Pulver", nutriments={}))
    f = res.findings[0]
    assert f["verdict"] == "nicht_pruefbar" and f["suggestion"] == "" and "nicht prüfbar" in f["reason"]
    assert "cannot be checked" in f["reason_en"]


def test_finding_has_rule_and_suggestion_without_the_claim():
    p = product("Bio High Protein Riegel Erdnuss", nutriments=LOW)
    f = run(p).findings[0]
    assert f["claim"] == "High Protein" and f["suggestion"] == "Bio Riegel Erdnuss"
    assert f["rule"].startswith("Anhang VO (EG) 1924/2006") and f["rule_en"].startswith("Annex to Reg. (EC) 1924/2006")
    assert "Nährwertangabe nicht erfüllt" in f["reason"] and "Nutrition claim not met" in f["reason_en"]


def test_claim_in_label_list_only_removes_the_claim():
    p = product("Riegel", labels="High proteins, No gluten, Carbon compensated product, Vegan", nutriments=LOW)
    f = run(p).findings[0]
    assert f["claim"] == "High proteins" and f["suggestion"] == "No gluten, Carbon compensated product, Vegan"


def test_labels_and_names_are_no_claims():
    for text in ("Vegan", "No gluten", "Bio", "Carbon compensated product", "Whey Protein Isolate", "Protein Riegel"):
        res = run(product("Shake", labels=text))
        assert res.findings == [] and res.suspicious == 0, text


def test_no_added_sugar_checks_the_ingredients():
    ok = product("Riegel", labels="Ohne Zuckerzusatz", ingredients="Milcheiweiß, Süßungsmittel (Maltit, Polydextrose), "
                 "Oligofruktosesirup, Maltitsirup, Zuckerkulör. Enthält von Natur aus Zucker.")
    bad = product("Riegel", labels="No added sugar", ingredients="Whey, sugar, cocoa")
    none = product("Riegel", labels="No added sugar", ingredients="")
    assert run(ok).findings == []
    assert run(bad).findings[0]["verdict"] == "nicht_erfuellt"
    assert run(none).findings[0]["verdict"] == "nicht_pruefbar"


def test_sugar_and_fat_thresholds():
    n = {"energy-kcal_100g": 380, "sugars_100g": 4.4, "fat_100g": 3.2}
    assert run(product("Riegel", labels="zuckerarm oder zuckerfrei", nutriments=n)).findings == []
    assert run(product("Riegel", labels="Low sugar", nutriments=n)).findings == []
    assert len(run(product("Riegel", labels="Zuckerfrei", nutriments=n)).findings) == 1
    assert len(run(product("Riegel", labels="Low fat", nutriments=n)).findings) == 1


def test_calcium_and_fibre_claims_are_not_checkable_without_data():
    for label in ("Calcium source", "ballaststoffreich", "Source of fibre"):
        assert run(product("Riegel", labels=label)).findings[0]["verdict"] == "nicht_pruefbar", label


def test_real_claim_next_to_nutrition_claim_still_goes_to_the_model():
    pre = prefilter(product("Riegel", description="High Protein Riegel. Das Produkt verbrennt Fett."))
    assert pre.suspicious == ["Das Produkt verbrennt Fett."]


def claim_codes(r):
    return [f["code"] for f in r["findings"] if f["check"] == "claims"]


def test_check_product_status_and_codes():
    r = check_product(product("Riegel", labels="High proteins", nutriments=LOW, source="brand"), NoCallLLM())
    assert claim_codes(r) == ["claim_nutrition"] and r["checks"]["claims"] == "red"
    off = check_product(product("Riegel", labels="High proteins", nutriments=LOW, source="off"), NoCallLLM())
    assert off["checks"]["claims"] == "yellow"
    unk = check_product(product("Riegel", labels="High proteins", nutriments={}, source="off"), NoCallLLM())
    assert claim_codes(unk) == ["claim_unverifiable"] and unk["checks"]["claims"] == "yellow"


def test_rescore_replaces_old_model_finding_for_nutrition_claims(tmp_path):
    p = product("LifeBar High Protein", nutriments=LOW, source="off")
    r = check_product(p, NoCallLLM())
    old = dict(r, findings=[{"check": "claims", "code": "claim_pruefen", "severity": "warn", "message": "x",
                             "claim": "LifeBar High Protein", "suggestion": "Quelle von Eiweiß, falls ..."},
                            {"check": "claims", "code": "claim_unzulaessig", "severity": "warn", "message": "y",
                             "claim": "Das heilt alles."}])
    data = {"meta": {"generated": "x", "model": "m", "mode": "claude", "placeholder": False, "api_cost_usd": 0.0008},
            "results": [old]}
    out = rescore(data)
    codes = [f["code"] for f in out["results"][0]["findings"] if f["check"] == "claims"]
    assert codes == ["claim_unzulaessig", "claim_nutrition"]
    assert out["meta"]["api_cost_usd"] == 0.0008 and out["meta"]["placeholder"] is False
    assert all("Quelle von Eiweiß" not in f.get("suggestion", "") for f in out["results"][0]["findings"])


def test_check_nutrition_reports_each_claim_once():
    p = product("LifeBar High Protein", labels="High proteins", nutriments=LOW)
    assert [c["key"] for c in check_nutrition(p)] == ["protein_high"]
    assert nutrition_finding(check_nutrition(p)[0], p)["verdict"] == "nicht_erfuellt"
