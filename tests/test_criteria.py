import json
import subprocess
from pathlib import Path
import pytest
from jd2candidates import criteria
from jd2candidates.criteria import SpecError, validate_spec

FX = Path(__file__).parent / "fixtures"


def load():
    return json.loads((FX / "spec_oracle.json").read_text())


def test_fixture_spec_validates():
    validate_spec(load())


def test_missing_country_named():
    s = load(); del s["hard"]["country_code"]
    with pytest.raises(SpecError, match="hard.country_code"):
        validate_spec(s)


def test_soft_levels_must_be_three():
    s = load(); s["soft"][0]["levels"] = ["a", "b"]
    with pytest.raises(SpecError, match=r"soft\[0\].levels"):
        validate_spec(s)


def test_empty_soft_rejected():
    s = load(); s["soft"] = []
    with pytest.raises(SpecError, match="soft"):
        validate_spec(s)


def test_jd_to_spec_parses_fenced_json_and_forces_thresholds(monkeypatch):
    s = load(); s["thresholds"] = {"good_must_have_min": 9}; s["search"]["geo_ids"] = ["102713980"]
    out = "Here you go:\n```json\n" + json.dumps(s) + "\n```\n"
    seen = {}
    def run(argv, **k):
        seen["argv"] = argv; seen["input"] = k.get("input")
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=out, stderr="")
    monkeypatch.setattr(subprocess, "run", run)
    spec = criteria.jd_to_spec("JD TEXT")
    assert seen["argv"][:5] == ["claude", "-p", "--model", "sonnet", "--output-format"]
    assert "JD TEXT" in seen["input"]
    assert spec["thresholds"] == criteria.THRESHOLDS
    assert spec["slug"] == "oracle-c2m-tech-lead-india"


def test_jd_to_spec_fills_geo_ids_when_empty(monkeypatch):
    s = load(); s["search"]["geo_ids"] = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **k: subprocess.CompletedProcess(args=argv, returncode=0, stdout=json.dumps(s), stderr=""))
    monkeypatch.setattr(criteria.treg, "call", lambda tool, params: ({"elements": [{"geoId": "102713980", "title": "India"}]}, 0.0))
    assert criteria.jd_to_spec("x")["search"]["geo_ids"] == ["102713980"]


def test_validate_rejects_boolean_over_300_chars():
    import json, pytest
    from pathlib import Path
    from jd2candidates import criteria
    spec = json.loads((Path(__file__).parent / "fixtures" / "spec_oracle.json").read_text())
    spec["search"]["boolean"] = "x" * 301
    with pytest.raises(criteria.SpecError, match="300"):
        criteria.validate_spec(spec)
