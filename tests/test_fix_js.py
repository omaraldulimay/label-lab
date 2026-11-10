"""Prueft die Logik hinter "Korrektur uebernehmen" (web/fix.js) mit Node, ohne Browser."""
import json
import shutil
import subprocess

import pytest

from labellab.llm import FakeLLM
from labellab.pipeline import ROOT, check_product, load_products

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node fehlt")

SCRIPT = """
const Fix = require(process.argv[1]);
const {r, applied} = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const claims = applied.map((i) => r.findings[i]);
const d = Fix.diff(r.product, r.name, claims);
console.log(JSON.stringify({eff: Fix.effective(r, applied), desc: Fix.joinSegs(d.description, ' '),
  name: Fix.joinSegs(d.name), generic: Fix.joinSegs(d.generic_name),
  can: r.findings.map((f) => Fix.canApply(f, r.product, r.name))}));
"""


def run_js(r, applied):
    out = subprocess.run(["node", "-e", SCRIPT, str(ROOT / "web" / "fix.js")],
                         input=json.dumps({"r": r, "applied": applied}), capture_output=True, text=True,
                         check=True).stdout
    return json.loads(out)


def result_for(code):
    p = next(p for p in load_products() if p["code"] == code)
    return p, check_product(p, FakeLLM())


def claim_idx(r):
    return [i for i, f in enumerate(r["findings"]) if f["check"] == "claims"]


def test_apply_turns_light_and_replaces_sentence():
    p, r = result_for("RF-1005")  # nur ein Claim Fund, sonst sauber
    assert r["status"] == "red"
    idx = claim_idx(r)
    out = run_js(r, idx)
    assert out["eff"]["status"] == "green" and out["eff"]["checks"]["claims"] == "green"
    assert r["findings"][idx[0]]["suggestion"] in out["desc"] and "Fettverbrennung" not in out["desc"]
    assert p["description"].split(". ")[-1].rstrip(".") in out["desc"]  # uebrige Saetze bleiben


def test_apply_matches_a_fresh_python_check():
    """Die Annahme "Vorschlag ist zulaessig" gilt im Fake: Neupruefung des geaenderten Texts bestaetigt das JS."""
    p, r = result_for("RF-1093")  # Fatburner steht in Name, Bezeichnung und Beschreibung
    out = run_js(r, claim_idx(r))
    fixed = dict(p, name=out["name"], generic_name=out["generic"], description=out["desc"])
    again = check_product(fixed, FakeLLM())
    assert again["checks"]["claims"] == "green" and "Fatburner" not in out["name"]
    assert out["eff"]["checks"]["claims"] == "green"


def test_partial_apply_keeps_other_findings():
    _, r = result_for("RF-1073")  # Immunsystem und Erkältungen im selben Satz
    idx = claim_idx(r)
    assert len(idx) == 2
    out = run_js(r, idx[:1])
    assert out["eff"]["status"] == "red" and len(out["eff"]["open"]) == len(r["findings"]) - 1


def test_rule_findings_cannot_be_applied():
    _, r = result_for("RF-1014")
    assert not any(run_js(r, [])["can"])
