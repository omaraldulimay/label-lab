from labellab.rules import check_contradictions, check_gaps

FULL = {"energy-kcal_100g": 400, "fat_100g": 5, "saturated-fat_100g": 2, "carbohydrates_100g": 20,
        "sugars_100g": 5, "proteins_100g": 68, "salt_100g": 0.5}


def prod(**n):
    nut = {**FULL, **n}
    nut = {k: v for k, v in nut.items() if v is not None}
    return {"code": "1", "name": "x", "ingredients": "Molkenprotein", "serving_size": "30 g", "nutriments": nut}


def codes(findings):
    return {f["code"] for f in findings}


def test_clean_product_has_no_findings():
    p = prod()
    assert check_gaps(p) == [] and check_contradictions(p) == []


def test_missing_single_nutrient_is_warning():
    f = check_gaps(prod(salt_100g=None))
    assert codes(f) == {"naehrwerte_fehlen"} and f[0]["severity"] == "warn" and "Salz" in f[0]["message"]


def test_many_missing_nutrients_is_error():
    p = prod(salt_100g=None, sugars_100g=None, fat_100g=None, proteins_100g=None)
    assert check_gaps(p)[0]["severity"] == "error"


def test_missing_ingredients_and_serving():
    p = prod()
    p["ingredients"], p["serving_size"] = "  ", ""
    assert codes(check_gaps(p)) == {"zutaten_fehlen", "portion_fehlt"}


def test_sugar_above_carbs():
    assert "zucker_ueber_kohlenhydrate" in codes(check_contradictions(prod(sugars_100g=25, **{"energy-kcal_100g": 400})))


def test_sugar_equal_to_carbs_is_fine():
    assert "zucker_ueber_kohlenhydrate" not in codes(check_contradictions(prod(sugars_100g=20)))


def test_saturated_above_fat():
    assert "gesaettigt_ueber_fett" in codes(check_contradictions(prod(**{"saturated-fat_100g": 9})))


def test_kcal_deviation_over_15_percent():
    # berechnet 4*68+4*20+9*5 = 397, angegeben 520 -> 31 %
    assert "kalorien_abweichung" in codes(check_contradictions(prod(**{"energy-kcal_100g": 520})))


def test_kcal_deviation_within_tolerance():
    assert "kalorien_abweichung" not in codes(check_contradictions(prod(**{"energy-kcal_100g": 430})))


def test_kcal_check_skipped_when_macros_missing():
    assert "kalorien_abweichung" not in codes(check_contradictions(prod(fat_100g=None, **{"energy-kcal_100g": 900})))


def test_value_above_100g():
    assert "wert_ueber_100g" in codes(check_contradictions(prod(proteins_100g=120)))
