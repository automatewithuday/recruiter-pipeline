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
        return (MISS if params["url"].lower().endswith("acw001") else RAW), 0.0064
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
    assert good and good[0]["stack_years"] and good[0]["review_notes"].startswith("Scoring unsure on: ")
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


def test_profile_pairs_with_its_candidate_when_another_is_missing(tmp_path, monkeypatch):
    from jd2candidates import discover
    monkeypatch.chdir(tmp_path)
    _fakes(monkeypatch, {"treg": 0, "jev": 0})
    leads = [e for e in LEADS["elements"] if e.get("linkedinUrl")]
    urls = [discover.norm_url(e["linkedinUrl"]) for e in leads]
    miss = urls[1]  # a miss in the middle, with HarvestAPI canonicalising every other URL
    def call(tool, params):
        if tool.endswith("leads.search"):
            return (LEADS if params["page"] == "1" else {"elements": []}), 0.10
        if params["url"] == miss:
            return MISS, 0.0064
        raw = json.loads(json.dumps(RAW)); n = urls.index(params["url"])
        raw["element"].update(firstName=f"P{n}", lastName="", linkedinUrl=f"https://www.linkedin.com/in/canon-{n}")
        return raw, 0.0064
    monkeypatch.setattr(pipeline, "_call", call)
    out = pipeline.run(FX / "jd_oracle.md", budget_usd=10, from_stage=1, source="harvest", yes=True)
    rows = list(csv.DictReader(open(out)))
    missing = [r for r in rows if r["gate_notes"] == "profile_missing"]
    assert [r["full_name"] for r in missing] == [discover._row(leads[1], "x")["name"]]
    assert {r["full_name"] for r in rows if r not in missing} == {f"P{n}" for n in range(len(urls)) if n != 1}


def test_over_range_candidate_is_capped_at_possible_fit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _fakes(monkeypatch, {"treg": 0, "jev": 0})
    spec = json.loads(json.dumps(SPEC)); spec["hard"]["max_total_years"] = 5  # every fixture profile is over range
    monkeypatch.setattr(criteria, "jd_to_spec", lambda text: spec)
    out = pipeline.run(FX / "jd_oracle.md", budget_usd=10, from_stage=1, source="harvest", yes=True)
    rows = [r for r in csv.DictReader(open(out)) if r["gate_notes"] != "profile_missing"]
    assert rows and all(r["tier"] == "Possible Fit" and "over_range" in r["gate_notes"] for r in rows)


def test_getleads_count_in_estimate_and_as_source(tmp_path, monkeypatch, capsys):
    from jd2candidates import getleads
    monkeypatch.chdir(tmp_path)
    c = {"treg": 0, "jev": 0}
    _fakes(monkeypatch, c)
    monkeypatch.setenv("GETLEADS_API_KEY", "glb_live_x")
    calls = []
    def post(url, body, headers):
        calls.append(url)
        if url.endswith("/count"):
            return {"ok": True, "total_matching": 1261}
        return {"ok": True, "has_more": False, "contacts": [
            {"full_name": "Asha K", "linkedin_url": "https://www.linkedin.com/in/asha-k", "current_title": "Technical Lead", "contact_location": "Pune"}]}
    monkeypatch.setattr(pipeline, "_gl_post", post)
    out = pipeline.run(FX / "jd_oracle.md", budget_usd=10, from_stage=1, source="getleads", yes=True)
    assert "GetLeads pool: 1261 (1261 credits to pull)" in capsys.readouterr().out
    rows = list(csv.DictReader(open(out)))
    assert len(rows) == 1 and rows[0]["source"] == "getleads" and rows[0]["full_name"] == "Asha K"
    assert not any(u.endswith("leads.search") for u in calls) and c["treg"] == 1  # one profile fetch, no lead search


def test_source_both_merges_and_dedupes_harvest_and_getleads(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    c = {"treg": 0, "jev": 0}
    _fakes(monkeypatch, c)
    monkeypatch.setenv("GETLEADS_API_KEY", "glb_live_x")
    first = LEADS["elements"][0]["linkedinUrl"]  # also returned by GetLeads, spelt differently
    def post(url, body, headers):
        if url.endswith("/count"):
            return {"ok": True, "total_matching": 2}
        return {"ok": True, "has_more": False, "contacts": [
            {"full_name": "Dup Person", "linkedin_url": first.replace("https://www.", "http://") + "/", "current_title": "Lead"},
            {"full_name": "Only GL", "linkedin_url": "https://www.linkedin.com/in/only-gl", "current_title": "Technical Lead"}]}
    monkeypatch.setattr(pipeline, "_gl_post", post)
    out = pipeline.run(FX / "jd_oracle.md", budget_usd=10, from_stage=1, source="both", yes=True)
    rows = list(csv.DictReader(open(out)))
    assert len(rows) == 24  # 23 from harvest + 1 only in GetLeads; the duplicate is one row
    assert sum(r["source"] == "getleads" for r in rows) == 1 and sum(r["full_name"] == "Dup Person" for r in rows) == 0
    report = (out.parent / "report.md").read_text()
    assert "getleads: 1" in report


def test_shortlist_has_good_fits_only_with_recruiter_columns(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _fakes(monkeypatch, {"treg": 0, "jev": 0})
    out = pipeline.run(FX / "jd_oracle.md", budget_usd=10, from_stage=1, source="harvest", yes=True)
    rows = list(csv.DictReader(open(out.parent / "shortlist.csv")))
    assert rows and all(r["tier"] == "Good Fit" for r in rows)
    assert list(rows[0]) == ["tier", "full_name", "current_title", "company", "location", "linkedin_url", "total_years", "stack_years",
                             "fit_reasoning", "ask_on_call", "gate_notes", "review_notes"]


def test_review_notes_are_readable_dimension_names(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _fakes(monkeypatch, {"treg": 0, "jev": 0})
    out = pipeline.run(FX / "jd_oracle.md", budget_usd=10, from_stage=1, source="harvest", yes=True)
    good = [r for r in csv.DictReader(open(out)) if r["tier"] == "Good Fit"]
    assert good[0]["review_notes"] == "Scoring unsure on: " + next(d["name"] for d in SPEC["soft"] if d["id"] == "integrations")
