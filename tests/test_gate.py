import json
from datetime import date
from pathlib import Path
import pytest
from jd2candidates import gate

FX = Path(__file__).parent / "fixtures"
HARD = json.loads((FX / "spec_oracle.json").read_text())["hard"]
TODAY = date(2026, 11, 13)


def exp(title, start, end, desc=""):
    return {"title": title, "company": "Co", "description": desc, "skills": [], "start": start, "end": end}


def prof(experience, country="IN"):
    return {"country_code": country, "experience": experience, "skills": [], "headline": "", "about": ""}


def test_months_missing_month_defaults():
    assert gate.months({"year": 2015, "month": None}, {"year": 2018, "month": None}, TODAY) == 48


def test_months_open_ended_uses_today():
    assert gate.months({"year": 2024, "month": 11}, None, TODAY) == 24


def test_merge_overlapping_ranges():
    r = gate.merge_ranges([(date(2016, 1, 1), date(2020, 12, 31)), (date(2018, 1, 1), date(2022, 12, 31))])
    assert r == [(date(2016, 1, 1), date(2022, 12, 31))]


def test_stack_years_case_insensitive_and_merged():
    p = prof([exp("cc&b developer", {"year": 2016, "month": 1}, {"year": 2020, "month": 12}),
              exp("MDM Lead", {"year": 2018, "month": 1}, {"year": 2022, "month": 12}),
              exp("Java Dev", {"year": 2010, "month": 1}, {"year": 2015, "month": 12})])
    g = gate.apply(p, HARD, TODAY)
    assert g["stack_years"]["value"] == pytest.approx(7.0, abs=0.1)
    assert g["stack_years"]["result"] == "fail"  # 7 < 8
    assert g["total_years"]["value"] == pytest.approx(16.9, abs=0.1)
    assert g["passed"] is False


def test_pass_when_bars_met():
    p = prof([exp("C2M Technical Lead", {"year": 2014, "month": 1}, None, "OUAF"),
              exp("Java Dev", {"year": 2012, "month": 1}, {"year": 2013, "month": 12})])
    g = gate.apply(p, HARD, TODAY)
    assert g["passed"] is True and g["stack_years"]["result"] == "pass" and g["country"]["result"] == "pass"


def test_country_unverified_when_missing():
    g = gate.apply(prof([exp("C2M Lead", {"year": 2010, "month": 1}, None)], country=None), HARD, TODAY)
    assert g["country"]["result"] == "unverified" and g["passed"] is True


def test_country_fail_when_different():
    g = gate.apply(prof([exp("C2M Lead", {"year": 2010, "month": 1}, None)], country="US"), HARD, TODAY)
    assert g["country"]["result"] == "fail" and g["passed"] is False


def test_unverified_when_no_dated_experience():
    g = gate.apply(prof([exp("C2M Lead", None, None)]), HARD, TODAY)
    assert g["total_years"]["result"] == "unverified" and g["stack_years"]["result"] == "unverified"
    assert g["passed"] is True


def test_excluded_current_title():
    p = prof([exp("QA Tester", {"year": 2010, "month": 1}, None, "C2M testing")])
    g = gate.apply(p, HARD, TODAY, exclude_titles=["Tester"])
    assert g["excluded_title"]["result"] == "fail" and g["excluded_title"]["value"] == "QA Tester"


def test_stack_years_near_miss_and_undated_mention_are_flagged_not_failed():
    hard = {**HARD, "min_stack_years": 8, "stack_years_floor": 5}
    near = gate.apply(prof([exp("CC&B Lead", {"year": 2020, "month": 11}, None), exp("Dev", {"year": 2010, "month": 1}, {"year": 2020, "month": 10})]), hard, TODAY)
    assert near["stack_years"] == {"result": "below_bar", "value": 6.0} and near["passed"]
    assert gate.apply(prof([exp("CC&B Lead", {"year": 2020, "month": 11}, None)]), {**HARD, "min_stack_years": 8}, TODAY)["stack_years"]["result"] == "fail"
    undated = prof([exp("Senior Consultant", {"year": 2010, "month": 1}, None)])
    assert gate.apply(undated, hard, TODAY)["stack_years"]["result"] == "fail"
    undated["headline"] = "Oracle Utilities CC&B specialist"
    g = gate.apply(undated, hard, TODAY)
    assert g["stack_years"] == {"result": "unverified", "value": 0.0} and g["passed"]


def test_total_years_over_range_is_flagged_not_failed():
    from datetime import date
    prof = {"country_code": "IN", "headline": "", "about": "", "skills": [],
            "experience": [{"title": "CC&B Lead", "company": "X", "description": "", "skills": [], "start": {"year": 2004, "month": 1}, "end": None}]}
    hard = {"country_code": "IN", "min_total_years": 10, "max_total_years": 18, "min_stack_years": 8, "stack_terms": ["CC&B"]}
    g = gate.apply(prof, hard, date(2026, 11, 13))
    assert g["total_years"] == {"result": "over_range", "value": 22.8} and g["passed"]
    hard["max_total_years"] = 0  # unstated in the JD: no cap
    assert gate.apply(prof, hard, date(2026, 11, 13))["total_years"]["result"] == "pass"
