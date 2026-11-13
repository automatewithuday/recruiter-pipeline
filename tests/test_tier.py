import json
from pathlib import Path
import pytest
from jd2candidates import tier, typesafe

FX = Path(__file__).parent / "fixtures"
SPEC = json.loads((FX / "spec_oracle.json").read_text())
RESP = json.loads((FX / "typesafe_response.json").read_text())
PROFILE = json.loads((FX / "profile_raw.json").read_text())
IDS = [d["id"] for d in SPEC["soft"]]


def scores(**over):
    base = {i: {"score": 1.3, "confidence": 0.9} for i in IDS}
    for k, v in over.items():
        base[k] = {"score": v, "confidence": 0.9}
    return base


def test_build_questions_shape():
    q = tier.build_questions(SPEC["soft"])
    assert set(q) == set(IDS)
    assert q["ouaf_hands_on"]["type"] == "score"
    assert q["ouaf_hands_on"]["criteria"] == SPEC["soft"][0]["levels"]
    assert SPEC["soft"][0]["name"] in q["ouaf_hands_on"]["instructions"]


def test_assign_good_fit():
    r = tier.assign(scores(ouaf_hands_on=1.3, stack_breadth=1.2, end_to_end=1.5, integrations=1.0, leadership=1.0, client_facing=1.0), SPEC)
    assert r["tier"] == "Good Fit" and r["mean"] == pytest.approx(1.1667, abs=1e-3)


def test_assign_possible_when_must_have_low():
    assert tier.assign(scores(stack_breadth=0.9), SPEC)["tier"] == "Possible Fit"


def test_assign_possible_when_mean_low_but_must_haves_ok():
    assert tier.assign(scores(integrations=0.2, leadership=0.2, client_facing=0.2), SPEC)["tier"] == "Possible Fit"


def test_assign_not_fit_when_must_have_absent():
    assert tier.assign(scores(end_to_end=0.4), SPEC)["tier"] == "Not a Fit"


def test_low_confidence_in_review_notes():
    s = scores(); s["integrations"] = {"score": 1.8, "confidence": 0.3}
    r = tier.assign(s, SPEC)
    assert r["review_notes"] == ["integrations"] and r["tier"] == "Good Fit"


def test_system_one_posts_expected_body(monkeypatch):
    seen = {}
    def post(url, body, headers):
        seen.update(url=url, body=body, headers=headers); return RESP
    out = typesafe.system_one({"a": 1}, {"q": {"type": "score", "instructions": "x", "criteria": ["a", "b", "c"]}}, "KEY", post=post)
    assert seen["url"] == "https://api.typesafe.ai/v1/systemone"
    assert seen["body"] == {"model": "jev-latest", "state": {"a": 1}, "questions": {"q": {"type": "score", "instructions": "x", "criteria": ["a", "b", "c"]}}}
    assert seen["headers"]["Authorization"] == "Bearer KEY"
    assert out == RESP


def test_retry_on_429_then_fail(monkeypatch):
    calls = []
    monkeypatch.setattr(typesafe.time, "sleep", lambda s: calls.append(s))
    def post(url, body, headers):
        raise typesafe.HTTPStatus(429)
    with pytest.raises(typesafe.TypeSafeError):
        typesafe.system_one({}, {}, "K", post=post)
    assert calls == [2, 4, 8]


def test_score_profile_maps_answers_and_state(monkeypatch):
    seen = {}
    def post(url, body, headers):
        seen["body"] = body; return RESP
    from jd2candidates.profile import trim
    s = tier.score_profile(trim(PROFILE), SPEC, "K", post=post)
    assert s["ouaf_hands_on"] == {"score": 1.7, "confidence": 0.8}
    st = seen["body"]["state"]
    assert set(st) == {"headline", "about", "skills", "certifications", "experience"}
    assert st["experience"][0]["title"] == "Technical Lead" and st["experience"][0]["years"] == pytest.approx(5.7, abs=0.1)
    assert set(seen["body"]["questions"]) == set(IDS)


def test_score_profile_returns_error_on_failure():
    def post(url, body, headers):
        raise typesafe.TypeSafeError("boom")
    assert tier.score_profile({"experience": []}, SPEC, "K", post=post) == {"error": "jev_failed"}
