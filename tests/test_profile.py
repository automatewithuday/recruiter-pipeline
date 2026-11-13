import json
from pathlib import Path
from jd2candidates import profile
from jd2candidates.budget import Budget

FX = Path(__file__).parent / "fixtures"
RAW = json.loads((FX / "profile_raw.json").read_text())
MISS = json.loads((FX / "profile_miss.json").read_text())


def test_trim_keeps_needed_fields():
    t = profile.trim(RAW)
    assert t["linkedin_url"] == "https://www.linkedin.com/in/asha-k" and t["full_name"] == "Asha K"
    assert t["country_code"] == "IN" and t["location_text"] == "Pune, Maharashtra, India"
    assert t["skills"] == ["Oracle CC&B", "Java"]
    assert t["certifications"] == ["Oracle Utilities CC&B Certified"]
    assert len(t["experience"]) == 3
    e0, e1 = t["experience"][0], t["experience"][1]
    assert e0["title"] == "Technical Lead" and e0["company"] == "Wipro" and e0["skills"] == ["C2M"]
    assert e0["start"] == {"year": 2021, "month": 3} and e0["end"] is None
    assert e1["start"] == {"year": 2016, "month": None} and e1["end"] == {"year": 2021, "month": 2}
    assert "companyLogo" not in json.dumps(t)


def test_trim_returns_none_on_miss():
    assert profile.trim(MISS) is None


def test_fetch_collects_missing_and_uses_url_param():
    seen = []
    def call(tool, params):
        seen.append((tool, params))
        return (MISS if params["url"].endswith("miss") else RAW), 0.0064
    cands = [{"linkedin_url": "https://www.linkedin.com/in/asha-k"}, {"linkedin_url": "https://www.linkedin.com/in/miss"}]
    out = profile.fetch_profiles(cands, Budget(10), call=call, workers=2)
    assert [p["full_name"] for p in out["profiles"]] == ["Asha K"]
    assert out["missing"] == ["https://www.linkedin.com/in/miss"]
    assert out["charged_usd"] == 0.0128
    assert all(t == "harvestapi.linkedin.user.profile" and set(p) == {"url"} for t, p in seen)


def test_fetch_stops_on_budget():
    call = lambda tool, params: (RAW, 0.0064)
    cands = [{"linkedin_url": f"https://www.linkedin.com/in/p{i}"} for i in range(6)]
    out = profile.fetch_profiles(cands, Budget(0.02), call=call, workers=1)
    assert out["stopped"] == "budget" and len(out["profiles"]) == 3
