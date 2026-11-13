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
    assert len(urls) == len(set(urls)) == 25  # 23 from p1 with url + 2 new on p2
    assert out["skipped_no_url"] == 2
    assert out["candidates"][0] == {"linkedin_url": "https://www.linkedin.com/in/ACw000", "name": "F0 L0",
                                    "headline": "Technical Lead", "location": "Pune, Maharashtra, India", "source": "harvest_leads"}


def test_stops_when_page_adds_fewer_than_3_new():
    out = discover.discover(SPEC, Budget(10), call=fake_call_factory([]))
    assert out["pages"] == 2 and out["charged_usd"] == pytest.approx(0.20)


def test_respects_max_pages():
    spec = json.loads(json.dumps(SPEC)); spec["search"]["max_pages"] = 1
    out = discover.discover(spec, Budget(10), call=fake_call_factory([]))
    assert out["pages"] == 1


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
