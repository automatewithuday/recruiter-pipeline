import csv
import json
from pathlib import Path
from jd2candidates import pipeline, criteria

FX = Path(__file__).parent / "fixtures"
SPEC = json.loads((FX / "spec_oracle.json").read_text())
LEADS = json.loads((FX / "leads_page1.json").read_text())
RAW = json.loads((FX / "profile_raw.json").read_text())
MISS = json.loads((FX / "profile_miss.json").read_text())
RESP = json.loads((FX / "typesafe_response.json").read_text())


def _fakes(monkeypatch, counter):
    def call(tool, params):
        counter["treg"] += 1
        if tool.endswith("leads.search"):
            return (LEADS if params["page"] == "1" else {"elements": []}), 0.10
        return (MISS if params["url"].endswith("ACw001") else RAW), 0.0064
    def post(url, body, headers):
        counter["jev"] += 1
        return RESP
    monkeypatch.setattr(pipeline, "_call", call)
    def ask(prompt):
        counter["ask"] = counter.get("ask", 0) + 1
        return json.dumps({str(i): {"reasoning": "Led CC&B at Co.", "ask_on_call": ["Which OUAF components?"]} for i in range(1, 6)})
    monkeypatch.setattr(pipeline, "_post", post)
    monkeypatch.setattr(pipeline, "_ask", ask)
    monkeypatch.setattr(criteria, "jd_to_spec", lambda text: json.loads(json.dumps(SPEC)))
    monkeypatch.setenv("TYPESAFE_API_KEY", "test")


def test_pipeline_end_to_end_with_fakes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    c = {"treg": 0, "jev": 0}
    _fakes(monkeypatch, c)
    out = pipeline.run(FX / "jd_oracle.md", budget_usd=10, from_stage=1, source="harvest", yes=True)
    rows = list(csv.DictReader(open(out)))
    assert out.name == "candidates.csv" and len(rows) == 23  # 23 with URL on page 1
    cols = list(rows[0])
    assert cols[:6] == ["tier", "full_name", "current_title", "company", "location", "linkedin_url"]
    assert "ouaf_hands_on" in cols and cols[-4:] == ["gate_notes", "review_notes", "fit_summary", "source"]
    tiers = [r["tier"] for r in rows]
    assert tiers == sorted(tiers, key=["Good Fit", "Possible Fit", "Not a Fit"].index)
    missing = [r for r in rows if r["gate_notes"] == "profile_missing"]
    assert len(missing) == 1 and missing[0]["tier"] == "Not a Fit"
    good = [r for r in rows if r["tier"] == "Good Fit"]
    assert good and good[0]["stack_years"] and good[0]["review_notes"] == "integrations"
    assert "strong" in good[0]["fit_summary"]
    report = (out.parent / "report.md").read_text()
    assert "Good Fit" in report and "USD" in report
    assert c["jev"] == 22
    assert good[0]["fit_reasoning"] == "Led CC&B at Co." and good[0]["ask_on_call"] == "1. Which OUAF components?"
    assert not missing[0]["fit_reasoning"]


def test_rerun_skips_cached_stages(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    c = {"treg": 0, "jev": 0}
    _fakes(monkeypatch, c)
    pipeline.run(FX / "jd_oracle.md", budget_usd=10, from_stage=1, source="harvest", yes=True)
    c.update(treg=0, jev=0, ask=0)
    pipeline.run(FX / "jd_oracle.md", budget_usd=10, from_stage=0, source="harvest", yes=True)
    assert c == {"treg": 0, "jev": 0, "ask": 0}


def test_estimate_over_budget_aborts(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _fakes(monkeypatch, {"treg": 0, "jev": 0})
    import pytest
    with pytest.raises(SystemExit):
        pipeline.run(FX / "jd_oracle.md", budget_usd=0.5, from_stage=1, source="harvest", yes=True)
    assert "estimate" in capsys.readouterr().out.lower()


def test_from_stage_recomputes_that_stage_onward(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    c = {"treg": 0, "jev": 0}
    _fakes(monkeypatch, c)
    pipeline.run(FX / "jd_oracle.md", budget_usd=10, from_stage=0, source="harvest", yes=True)
    c["treg"] = 0; c["jev"] = 0
    pipeline.run(FX / "jd_oracle.md", budget_usd=10, from_stage=3, source="harvest", yes=True)
    assert (c["treg"], c["jev"]) == (23, 22) and c["ask"] > 0  # profiles refetched, rescored, notes rewritten; discover stays cached
