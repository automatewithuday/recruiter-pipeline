import json
from pathlib import Path
import pytest
from jd2candidates import discover
from jd2candidates.budget import Budget

FX = Path(__file__).parent / "fixtures"
SPEC = json.loads((FX / "spec_oracle.json").read_text())
PAGES = {1: json.loads((FX / "leads_page1.json").read_text()), 2: json.loads((FX / "leads_page2.json").read_text())}


def fake_call_factory(seen, price=0.10):
    def call(tool, params):
        seen.append((tool, dict(params)))
        page = int(params["page"])
        return PAGES.get(page, {"elements": [], "pagination": {}}), price
    return call


def test_dedupes_and_counts_skipped():
    seen = []
    out = discover.discover(SPEC, Budget(10), call=fake_call_factory(seen))
    urls = [c["linkedin_url"] for c in out["candidates"]]
    assert len(urls) == len(set(urls)) == 25  # 23 from p1 with url + 2 new on p2; the other angles see the same people again
    assert out["skipped_no_url"] == 2 * 4  # the two URL-less rows on p1 are counted once per angle
    assert out["candidates"][0] == {"linkedin_url": "https://www.linkedin.com/in/ACw000", "name": "F0 L0",
                                    "headline": "Technical Lead", "location": "Pune, Maharashtra, India", "source": "harvest_leads"}


def test_stops_when_page_adds_fewer_than_3_new():
    out = discover.discover(SPEC, Budget(10), call=fake_call_factory([]))
    # first angle: p1 adds 23, p2 adds 2 -> stop; each of the other three angles sees nothing new on p1 -> stop
    assert out["pages"] == 5 and out["charged_usd"] == pytest.approx(0.50)
    assert out["angles"]["harvest_leads"] == 25


def test_respects_max_pages():
    spec = json.loads(json.dumps(SPEC)); spec["search"]["max_pages"] = 1
    out = discover.discover(spec, Budget(10), call=fake_call_factory([]))
    assert out["pages"] == 4  # one page per angle


def test_budget_exceeded_returns_partial():
    out = discover.discover(SPEC, Budget(0.15), call=fake_call_factory([]))
    assert out["pages"] == 1 and out["stopped"] == "budget" and out["charged_usd"] == pytest.approx(0.10)


def test_params_sent():
    seen = []
    spec = json.loads(json.dumps(SPEC)); spec["search"]["years_of_experience_ids"] = [4, 5]
    discover.discover(spec, Budget(10), call=fake_call_factory(seen))
    tool, p = seen[0]
    assert tool == "harvestapi.linkedin.leads.search"
    assert p["search"] == spec["search"]["boolean"]
    assert p["currentJobTitles"] == ",".join(spec["search"]["current_titles"])
    assert p["geoIds"] == "102713980" and p["yearsOfExperienceIds"] == "4,5"
    assert p["excludeCurrentJobTitles"] == ",".join(spec["search"]["exclude_titles"])
    assert p["page"] == "1"


def test_angles_run_in_order_and_dedupe_across_them():
    seen = []
    spec = json.loads(json.dumps(SPEC)); spec["search"]["max_pages"] = 1
    def call(tool, params):
        seen.append(dict(params))
        if "pastJobTitles" in params:  # the past-title angle finds 2 people the others did not
            return {"elements": [{"linkedinUrl": "https://www.linkedin.com/in/past1", "firstName": "P", "lastName": "1"},
                                 {"linkedinUrl": "https://www.linkedin.com/in/past2", "firstName": "P", "lastName": "2"},
                                 {"linkedinUrl": "https://www.linkedin.com/in/ACw000"}]}, 0.05
        return PAGES[1], 0.05
    out = discover.discover(spec, Budget(10), call=call)
    stack = ",".join(spec["search"]["stack_titles"])
    assert [(p.get("search"), p.get("currentJobTitles"), p.get("pastJobTitles")) for p in seen] == [
        (spec["search"]["boolean"], ",".join(spec["search"]["current_titles"]), None),
        (None, stack, None),
        (None, None, stack),
        (spec["search"]["boolean"], None, None)]
    assert all(p["geoIds"] == "102713980" and p["excludeCurrentJobTitles"] for p in seen)
    assert len(out["candidates"]) == 25 and out["pages"] == 4
    src = {c["linkedin_url"]: c["source"] for c in out["candidates"]}
    assert src["https://www.linkedin.com/in/ACw000"] == "harvest_leads"  # first angle keeps the person
    assert src["https://www.linkedin.com/in/past1"] == "harvest_leads:past_title_names_stack"
    assert out["angles"] == {"harvest_leads": 23, "harvest_leads:title_names_stack": 0,
                             "harvest_leads:past_title_names_stack": 2, "harvest_leads:keyword_no_title_filter": 0}


def test_keyword_only_angle_is_capped():
    spec = json.loads(json.dumps(SPEC)); spec["search"]["max_pages"] = 50
    n = {"kw_only": 0}
    def call(tool, params):
        if "search" in params and "currentJobTitles" not in params:
            n["kw_only"] += 1
        return {"elements": [{"linkedinUrl": f"https://www.linkedin.com/in/{params.get('pastJobTitles','')}{params.get('currentJobTitles','')}{len(params)}-{params['page']}-{i}"} for i in range(5)]}, 0.05
    discover.discover(spec, Budget(100), call=call)
    assert n["kw_only"] == discover.KEYWORD_ONLY_PAGES == 4
