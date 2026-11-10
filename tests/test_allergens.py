import pytest

from labellab.allergens import ALLERGENS, check_allergens, find_in_text, from_off_tags


def test_all_14_allergens_present():
    assert len(ALLERGENS) == 14


@pytest.mark.parametrize("text,key", [
    ("Molkenproteinisolat", "milch"), ("Casein", "milch"), ("Laktose", "milch"), ("whey protein", "milch"),
    ("Weizenmehl", "gluten"), ("oat flakes", "gluten"), ("Sojalecithin", "soja"), ("soy protein", "soja"),
    ("Erdnussmus", "erdnuesse"), ("peanut butter", "erdnuesse"), ("Mandeln", "schalenfruechte"),
    ("Hühnerei", "eier"), ("egg white", "eier"), ("Lachsöl", "fisch"), ("Sellerie", "sellerie"),
    ("Senfsaat", "senf"), ("Sesamöl", "sesam"), ("Schwefeldioxid", "sulfite"), ("Lupinenmehl", "lupine"),
    ("Garnelen", "krebstiere"), ("Muschelextrakt", "weichtiere"),
])
def test_synonyms(text, key):
    assert key in find_in_text(text)


@pytest.mark.parametrize("text,key", [
    ("Eiweißkonzentrat", "eier"),      # Eiweiss ist kein Ei
    ("Kakaobutter", "milch"),          # Butter nur am Wortanfang
    ("Code 123", "fisch"),
])
def test_no_false_positives(text, key):
    assert key not in find_in_text(text)


def test_off_tags_mapping():
    assert from_off_tags(["en:milk", "en:soybeans", "de:unbekannt"]) == {"milch", "soja"}


def test_undeclared_allergen_is_error():
    f = check_allergens("Molkenprotein, Aroma", [])
    assert f[0]["code"] == "allergen_nicht_deklariert" and f[0]["severity"] == "error"


def test_declared_allergen_ok():
    assert check_allergens("Molkenprotein", ["en:milk"]) == []


def test_declared_but_not_in_ingredients_is_warning():
    f = check_allergens("Reismehl", ["en:milk"])
    assert f[0]["code"] == "allergen_ohne_zutat" and f[0]["severity"] == "warn"


def test_traces_are_not_ingredients():
    assert check_allergens("Cashewkerne. Kann Spuren von Erdnüssen enthalten.", ["en:nuts"]) == []


def test_no_ingredients_no_check():
    assert check_allergens("", ["en:milk"]) == []
