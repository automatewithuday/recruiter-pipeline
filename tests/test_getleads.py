import json
from pathlib import Path
import pytest
from jd2candidates import getleads
from jd2candidates.typesafe import HTTPStatus

FX = Path(__file__).parent / "fixtures"
SPEC = json.loads((FX / "spec_oracle.json").read_text())
ROW = {"full_name": "Asha K", "linkedin_url": "https://www.linkedin.com/in/asha-k", "linkedin_headline": "CC&B Technical Lead",
       "current_title": "Technical Lead", "current_employer": "Wipro", "contact_location": "Pune, Maharashtra, India"}


def test_count_sends_filters_and_returns_total():
    seen = []
    def post(url, body, headers):
        seen.append((url, body, headers))
        return {"ok": True, "total_matching": 1261, "creditsRemaining": 6}
    n = getleads.count(SPEC, "glb_live_x", post=post)
    url, body, headers = seen[0]
    assert n == 1261 and url.endswith("/api/v1/contacts/search/count") and headers == {"X-API-Key": "glb_live_x"}
    assert body["countries"] == ["India"]
    assert body["linkedin_headline"] == "Oracle Utilities,C2M,CC&B,CCB,OUAF,Customer Care and Billing"  # the boolean's OR terms, unquoted
    assert body["exclude_job_titles"] == SPEC["search"]["exclude_titles"]


def test_search_pages_and_maps_rows():
    pages = iter([{"ok": True, "contacts": [ROW], "has_more": True, "next_offset": 1, "credits_exhausted": False},
                  {"ok": True, "contacts": [{**ROW, "linkedin_url": "https://www.linkedin.com/in/b"}], "has_more": False}])
    seen = []
    def post(url, body, headers):
        seen.append(body); return next(pages)
    out = getleads.search(SPEC, "k", post=post)
    assert [c["linkedin_url"] for c in out["candidates"]] == ["https://www.linkedin.com/in/asha-k", "https://www.linkedin.com/in/b"]
    assert out["candidates"][0] == {"linkedin_url": "https://www.linkedin.com/in/asha-k", "name": "Asha K", "headline": "Technical Lead",
                                    "location": "Pune, Maharashtra, India", "source": "getleads"}
    assert [b["offset"] for b in seen] == [0, 1] and all(b["limit"] == 100 and "columns" in b for b in seen)
    assert out["credits_used"] == 2 and "stopped" not in out


def test_search_stops_cleanly_when_credits_run_out():
    def post(url, body, headers):
        if body["offset"] == 0:
            return {"ok": True, "contacts": [ROW], "has_more": True, "next_offset": 1}
        raise HTTPStatus(402, '{"code":"credits_exhausted","message":"Out of credits"}')
    out = getleads.search(SPEC, "k", post=post)
    assert len(out["candidates"]) == 1 and out["stopped"] == "credits"


def test_rows_without_linkedin_url_are_skipped():
    post = lambda url, body, headers: {"ok": True, "contacts": [ROW, {**ROW, "linkedin_url": ""}], "has_more": False}
    out = getleads.search(SPEC, "k", post=post)
    assert len(out["candidates"]) == 1 and out["skipped_no_url"] == 1


def test_count_polls_while_counting(monkeypatch):
    monkeypatch.setattr(getleads.time, "sleep", lambda s: None)
    polls = iter([{"ok": True, "status": "counting", "total_matching": None}, {"ok": True, "status": "done", "total_matching": 1261}])
    seen = []
    def post(url, body, headers):
        return {"ok": True, "status": "counting", "count_id": "abc", "total_matching": None, "retry_after_seconds": 10}
    def get(url, headers):
        seen.append(url); return next(polls)
    assert getleads.count(SPEC, "k", post=post, get=get) == 1261
    assert seen == [f"{getleads.BASE}/count/abc"] * 2
