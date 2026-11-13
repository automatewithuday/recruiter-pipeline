# JD → Tiered Candidate List Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One command turns a JD file into a CSV of LinkedIn candidates, every one profile-read, hard-gated in code, and tiered by Jev.

**Architecture:** Six stage modules under `jd2candidates/` pass plain dicts through a per-run JSON cache in `runs/<slug>/`. Paid calls go through the installed `treg` CLI (subprocess) and TypeSafe's HTTP API; Haiku runs through `claude -p`. A `Budget` object sums treg's reported charges and stops the run at the cap.

**Tech Stack:** Python 3.12 via uv, stdlib only at runtime (subprocess, json, csv, datetime, urllib, concurrent.futures), pytest as the only dev dependency.

**Spec:** `docs/specs/2026-11-13-jd-to-candidates-design.md`

## Global Constraints

- Python always via `uv run` / `uv add`; never bare python or pip.
- Secrets only in `.env`; never printed, logged, echoed, or committed. `.env` and `runs/` are gitignored.
- No Firecrawl anywhere in the pipeline.
- A profile is fetched once, from `harvestapi.linkedin.user.profile` only.
- Hard gates are computed in code; Jev never decides a hard gate.
- The pipeline never widens a search on its own.
- Default budget 10 USD per run; pre-run estimate shown; clean stop at the cap; resume from cache.
- Tier thresholds (relaxed, first runs): good_must_have_min 1.2, good_mean_min 1.1, possible_must_have_min 0.5, low_confidence 0.5.
- Paths in this project contain a space; always quote.

## Review Focus

1. Lead search rows with no `linkedinUrl` (anonymised "LinkedIn Member") must be skipped and counted, not crashed on or fetched. Test in Task 3.
2. A profile call that returns 200 but no `element` (hit miss) must mark the person `profile_missing` and exclude them with a note, not raise. Test in Task 4.
3. Experience entries with a year but no month, or no `endDate`, must still produce a tenure number. Test in Task 5.
4. TypeSafe `429` must back off and retry up to 3 times before marking the person `review: jev_failed`, never abort the run. Test in Task 6.
5. A JD with no location must fail spec validation with a message naming the missing field, before any paid call. Test in Task 2.

---

### Task 1: Scaffold, env, treg wrapper, cache

**Files:**
- Create: `pyproject.toml`, `jd2candidates/__init__.py`, `jd2candidates/env.py`, `jd2candidates/treg.py`, `jd2candidates/cache.py`, `jd2candidates/budget.py`
- Test: `tests/test_treg.py`, `tests/test_budget.py`

**Interfaces:**
- Produces:
  - `env.load() -> None` reads `.env` in the project root into `os.environ` without overwriting existing keys.
  - `treg.call(tool: str, params: dict[str, str]) -> tuple[dict, float]` runs `treg call <tool> -p k=v ...`, returns parsed stdout JSON and the USD charged parsed from stderr line `treg: charged $X`. Raises `TregError(stderr_text)` on non-zero exit.
  - `cache.RunDir(slug: str)` with `.path`, `.read(stage: str) -> dict | list | None`, `.write(stage: str, data) -> None` storing `runs/<slug>/<stage>.json`.
  - `budget.Budget(cap_usd: float)` with `.add(usd: float) -> None` (raises `BudgetExceeded` when total would exceed cap), `.spent -> float`.

- [ ] **Step 1: Initialise repo and project**

```bash
cd "/Users/udaykang/Firecrawl Recruitement" && git init && uv init --package --name jd2candidates --python 3.12 && uv add --dev pytest
```
Set `[project.scripts] jd2candidates = "jd2candidates.cli:main"` in `pyproject.toml`.

- [ ] **Step 2: Write failing tests**

```python
# tests/test_treg.py
def test_call_parses_json_and_charge(monkeypatch):
    fake = subprocess.CompletedProcess(args=[], returncode=0,
        stdout='{"elements":[{"geoId":"1"}]}',
        stderr='treg: charged $0.0064 · call id abc\n')
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: fake)
    data, usd = treg.call("harvestapi.linkedin.user.profile", {"url": "x"})
    assert data["elements"][0]["geoId"] == "1" and usd == 0.0064

def test_call_raises_on_failure(monkeypatch): ...  # returncode 1 -> TregError

# tests/test_budget.py
def test_budget_stops_at_cap():
    b = Budget(1.0); b.add(0.6)
    with pytest.raises(BudgetExceeded): b.add(0.5)
    assert b.spent == 0.6
```

- [ ] **Step 3: Run tests, confirm they fail**

Run: `uv run pytest -q`  Expected: ImportError / FAIL.

- [ ] **Step 4: Implement the four modules per Interfaces**

`treg.call` builds `["treg", "call", tool] + ["-p", f"{k}={v}" for each]`, `subprocess.run(..., capture_output=True, text=True)`, charge regex `charged \$([0-9.]+)` with default 0.0.

- [ ] **Step 5: Run tests, confirm pass**

Run: `uv run pytest -q`  Expected: 3 passed.

- [ ] **Step 6: Live smoke (free)**

Run: `uv run python -c 'from jd2candidates import treg; d,u=treg.call("harvestapi.linkedin.geo.search",{"search":"India"}); print(d["elements"][0], u)'`
Expected: `{'geoId': '102713980', 'title': 'India'} 0.0`

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: scaffold jd2candidates with treg wrapper, cache, budget"
```

---

### Task 2: criteria.py — JD to search spec

**Files:**
- Create: `jd2candidates/criteria.py`, `jd2candidates/prompts/criteria.md`, `tests/fixtures/spec_oracle.json`, `tests/fixtures/jd_oracle.md`
- Test: `tests/test_criteria.py`

**Interfaces:**
- Produces:
  - `criteria.jd_to_spec(jd_text: str) -> dict` runs `claude -p --model sonnet --output-format text` with the prompt file plus the JD, strips code fences, `json.loads`, then `validate_spec`. (Uday asked for Sonnet over Haiku here; one call per JD.)
  - `criteria.validate_spec(spec: dict) -> None` raises `SpecError("missing: <path>")` naming the first missing field.
  - Spec schema (exact keys later tasks read):

```json
{
  "slug": "oracle-c2m-tech-lead-india",
  "hard": {"country_code": "IN", "min_total_years": 10, "min_stack_years": 8,
           "stack_terms": ["C2M", "Customer to Meter", "CC&B", "CCB", "Customer Care and Billing",
                            "MDM", "Meter Data Management", "OUAF", "Oracle Utilities"]},
  "soft": [{"id": "ouaf_hands_on", "name": "Hands-on OUAF components", "must_have": true,
            "levels": ["No sign of ...", "Some ...", "Clear ..."]}],
  "search": {"boolean": "(\"Oracle Utilities\" OR C2M OR \"CC&B\" OR CCB OR OUAF)",
             "current_titles": ["Technical Lead", "Solution Architect"],
             "exclude_titles": ["Tester", "Recruiter", "Intern", "Student", "Trainer"],
             "geo_ids": ["102713980"], "years_of_experience_ids": ["4", "5"], "max_pages": 20},
  "thresholds": {"good_must_have_min": 1.2, "good_mean_min": 1.1,
                 "possible_must_have_min": 0.5, "low_confidence": 0.5}
}
```

- [ ] **Step 1: Write fixtures**

`tests/fixtures/jd_oracle.md` = the Oracle Utilities C2M JD text from the conversation. `tests/fixtures/spec_oracle.json` = a hand-written spec in the schema above with 6 soft dimensions: ouaf_hands_on (must), c2m_ccb_mdm_breadth (must), integrations, end_to_end_implementations (must), team_leadership, client_facing.

- [ ] **Step 2: Write failing tests**

```python
def test_fixture_spec_validates(): validate_spec(load("spec_oracle.json"))
def test_missing_country_named():
    s = load("spec_oracle.json"); del s["hard"]["country_code"]
    with pytest.raises(SpecError, match="hard.country_code"): validate_spec(s)
def test_soft_levels_must_be_three():
    s = load("spec_oracle.json"); s["soft"][0]["levels"] = ["a","b"]
    with pytest.raises(SpecError, match="soft\\[0\\].levels"): validate_spec(s)
def test_jd_to_spec_parses_fenced_json(monkeypatch):  # fake subprocess returning ```json ... ```
```

- [ ] **Step 3: Run tests, confirm fail.** `uv run pytest tests/test_criteria.py -q`

- [ ] **Step 4: Write `prompts/criteria.md`**

Instructions to Haiku: return only JSON in the schema; `levels` are three concrete evidence descriptions (absent, partial, strong) specific to this JD; `must_have` true for at most half the dimensions; `boolean` uses LinkedIn operators (AND, OR, NOT, quotes); `geo_ids` left empty for the code to fill; `thresholds` copied from the Global Constraints values; `years_of_experience_ids` from the map `1:<1y, 2:1-2y, 3:3-5y, 4:6-10y, 5:>10y` chosen from `min_total_years`.

- [ ] **Step 5: Implement `jd_to_spec` and `validate_spec`**

After parsing, if `search.geo_ids` is empty, fill it with `treg.call("harvestapi.linkedin.geo.search", {"search": hard.country_name})` first element (free). Always overwrite `thresholds` with the Global Constraints values.

- [ ] **Step 6: Run tests, confirm pass.**

- [ ] **Step 7: Live smoke**

Run: `uv run python -c 'from jd2candidates import criteria; import json; print(json.dumps(criteria.jd_to_spec(open("tests/fixtures/jd_oracle.md").read()), indent=1))'`
Expected: valid JSON, 5 to 8 soft dimensions, `geo_ids == ["102713980"]`. Eyeball the boolean string. Save output as `runs/oracle-c2m-tech-lead-india/spec.json` for Task 7.

- [ ] **Step 8: Commit.** `git commit -am "feat: criteria stage, JD to spec via Haiku"`

---

### Task 3: discover.py — lead search with dedupe and stop rules

**Files:**
- Create: `jd2candidates/discover.py`, `tests/fixtures/leads_page1.json`, `tests/fixtures/leads_page2.json`
- Test: `tests/test_discover.py`

**Interfaces:**
- Consumes: `treg.call`, `Budget`, spec `search` block.
- Produces: `discover.discover(spec: dict, budget: Budget, call=treg.call) -> dict` returning `{"candidates": [{"linkedin_url", "name", "headline", "location", "source": "harvest_leads"}], "pages": int, "skipped_no_url": int, "charged_usd": float}`.

- [ ] **Step 1: Fixtures**

Two pages shaped like HarvestAPI `lead-search` (`elements[]` with `linkedinUrl`, `firstName`, `lastName`, `summary`, `location.linkedinText`, `currentPositions[0].title`; `pagination.totalPages`). Page 1: 25 rows, 2 with `linkedinUrl: null`. Page 2: 25 rows of which 23 repeat page 1 (so only 2 new).

- [ ] **Step 2: Failing tests**

```python
def test_dedupes_and_counts_skipped(fake_call):   # 25+25 rows -> 25 unique with url, skipped_no_url == 2
def test_stops_when_page_adds_fewer_than_3_new(fake_call): # pages == 2
def test_respects_max_pages(fake_call):           # spec max_pages 1 -> pages == 1
def test_budget_exceeded_returns_partial(fake_call): # Budget(0.05) -> 1 page, no raise, charged_usd == 0.05
def test_params_sent(fake_call):  # search, currentJobTitles, geoIds, yearsOfExperienceIds, excludeCurrentJobTitles, page
```

- [ ] **Step 3: Run, confirm fail.**

- [ ] **Step 4: Implement `discover`**

Params: `search`=boolean, `currentJobTitles`=",".join(current_titles), `geoIds`=",".join(geo_ids), `yearsOfExperienceIds`=",".join(...), `excludeCurrentJobTitles`=",".join(exclude_titles), `page`=n. Loop pages 1..max_pages; dedupe on `linkedinUrl`; stop when a page adds fewer than 3 new; catch `BudgetExceeded` and return what was gathered with a `"stopped": "budget"` key.

- [ ] **Step 5: Run, confirm pass. Commit.** `git commit -am "feat: discover stage via HarvestAPI lead search"`

---

### Task 4: profile.py — full profile fetch and trim

**Files:**
- Create: `jd2candidates/profile.py`, `tests/fixtures/profile_raw.json`, `tests/fixtures/profile_miss.json`
- Test: `tests/test_profile.py`

**Interfaces:**
- Produces:
  - `profile.trim(raw: dict) -> dict | None` returns `None` when `raw.get("element")` is missing, else `{"linkedin_url", "full_name", "headline", "location_text", "country_code", "about", "skills": [str], "experience": [{"title", "company", "description", "skills": [str], "start": {"year", "month"}, "end": {"year", "month"} | None}]}`.
  - `profile.fetch_profiles(candidates: list[dict], budget: Budget, call=treg.call, workers: int = 5) -> dict` returning `{"profiles": [trimmed], "missing": [linkedin_url], "charged_usd": float}`.

- [ ] **Step 1: Fixtures.** `profile_raw.json` in HarvestAPI `element` shape with 3 experience entries (one with no month, one with no endDate). `profile_miss.json` = `{"status": 200, "element": null}`.

- [ ] **Step 2: Failing tests**

```python
def test_trim_keeps_needed_fields(): ...  # country_code "IN", 3 experience, start.month None preserved
def test_trim_returns_none_on_miss(): assert trim(load("profile_miss.json")) is None
def test_fetch_collects_missing(fake_call): # one miss -> in missing, not in profiles
def test_fetch_uses_url_param(fake_call):   # params == {"url": candidate["linkedin_url"]}
```

- [ ] **Step 3: Run, confirm fail. Step 4: Implement** with `ThreadPoolExecutor(max_workers=workers)`; `Budget.add` is called under a lock; on `BudgetExceeded` cancel remaining futures and return partial with `"stopped": "budget"`.

- [ ] **Step 5: Run, confirm pass. Commit.** `git commit -am "feat: profile stage, HarvestAPI full profile fetch and trim"`

---

### Task 5: gate.py — hard requirements from dates

**Files:**
- Create: `jd2candidates/gate.py`
- Test: `tests/test_gate.py`

**Interfaces:**
- Consumes: trimmed profile from Task 4, spec `hard`.
- Produces: `gate.apply(profile: dict, hard: dict, today: date) -> dict` returning `{"country": R, "total_years": R, "stack_years": R, "excluded_title": R, "passed": bool}` where `R = {"result": "pass"|"fail"|"unverified", "value": float|str|None}` and `passed` is False only if any result is `fail`.
- Helpers (tested directly): `months(start: dict, end: dict | None, today: date) -> int`, `merge_ranges(ranges: list[tuple[date, date]]) -> list[tuple[date, date]]`, `matches_stack(text: str, terms: list[str]) -> bool`.

- [ ] **Step 1: Failing tests**

```python
def test_months_missing_month_defaults():  # start {2015,None} end {2018,None} -> Jan..Dec = 48
def test_months_open_ended_uses_today():   # end None, today 2026-11-13
def test_merge_overlapping_ranges():       # two parallel stack roles 2016-2020, 2018-2022 -> 6 years not 8
def test_stack_years_case_insensitive():   # "cc&b developer" matches "CC&B"
def test_country_unverified_when_missing(): # country_code None -> unverified, passed True
def test_fail_on_short_stack_years():      # 5y vs min 8 -> fail, passed False
def test_excluded_current_title():         # current title "QA Tester" with exclude ["Tester"] -> fail
```

- [ ] **Step 2: Run, confirm fail. Step 3: Implement.** Total years = today minus earliest start. Stack years = merged months of entries where `matches_stack(title + " " + description)`. Current title = experience entry with `end is None`, first one.

- [ ] **Step 4: Run, confirm pass. Commit.** `git commit -am "feat: gate stage, hard requirements from experience dates"`

---

### Task 6: tier.py — Jev scores and tier assignment

**Files:**
- Create: `jd2candidates/typesafe.py`, `jd2candidates/tier.py`, `tests/fixtures/typesafe_response.json`
- Test: `tests/test_tier.py`

**Interfaces:**
- Produces:
  - `typesafe.system_one(state: dict, questions: dict, api_key: str, post=urllib_post) -> dict` POSTs `{"model": "jev-latest", "state": state, "questions": questions}` to `https://api.typesafe.ai/v1/systemone` with `Authorization: Bearer <key>`; on HTTP 429 sleeps 2s, 4s, 8s then raises `TypeSafeError`.
  - `tier.build_questions(soft: list[dict]) -> dict` → `{dim.id: {"type": "score", "instructions": "How strongly does this profile show: <name>?", "criteria": dim.levels}}`.
  - `tier.score_profile(profile: dict, spec: dict, api_key: str, post=...) -> dict` → `{dim.id: {"score": float, "confidence": float}}` or `{"error": "jev_failed"}`.
  - `tier.assign(scores: dict, spec: dict) -> dict` → `{"tier": "Good Fit"|"Possible Fit"|"Not a Fit", "mean": float, "review_notes": [dim.id with confidence < low_confidence]}`.

- [ ] **Step 1: Fixture.** `typesafe_response.json` = `{"answers": {"ouaf_hands_on": {"score": 1.7, "confidence": 0.8}, ...}}`. Builder confirms the real key names (`answers` vs top level) with one live call once the key exists and adjusts the parser; the fixture must then mirror the real shape.

- [ ] **Step 2: Failing tests**

```python
def test_build_questions_shape():            # type score, criteria == levels, one per dim
def test_assign_good_fit():                  # must-haves 1.3,1.2,1.5; others 1.0 -> mean>=1.1 -> Good Fit
def test_assign_possible_when_must_have_low(): # a must-have 0.9 -> Possible Fit
def test_assign_not_fit_when_must_have_absent(): # a must-have 0.4 -> Not a Fit
def test_low_confidence_in_review_notes():   # confidence 0.3 -> id listed, tier unchanged
def test_retry_on_429_then_fail(fake_post):  # 4x 429 -> TypeSafeError after 3 retries, score_profile returns {"error": "jev_failed"}
```

- [ ] **Step 3: Run, confirm fail. Step 4: Implement.** State sent to Jev = `{"headline", "about", "skills", "experience": [{"title", "company", "description", "years"}]}` built from the trimmed profile; `years` computed with `gate.months / 12` rounded to 1 decimal.

- [ ] **Step 5: Run, confirm pass. Commit.** `git commit -am "feat: tier stage, Jev scoring and tier assignment"`

---

### Task 7: export.py, cli.py, run report, end-to-end

**Files:**
- Create: `jd2candidates/export.py`, `jd2candidates/cli.py`, `jd2candidates/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Produces:
  - `export.write_csv(rows: list[dict], soft: list[dict], path: Path) -> None` with columns in this order: `tier, full_name, current_title, company, location, linkedin_url, total_years, stack_years, <one column per soft id>, gate_notes, review_notes, fit_summary, source`. Rows sorted Good Fit, Possible Fit, Not a Fit, then mean descending.
  - `export.write_report(stats: dict, path: Path) -> None` markdown with: pool found, skipped no-URL, profiles read, profiles missing, gate pass / fail / unverified counts, tier counts, charged USD per stage and total, stopped reason if any.
  - `pipeline.run(jd_path: Path, budget_usd: float, from_stage: int, with_getleads: bool) -> Path` orchestrates stages 1 to 6 with the cache: a stage whose JSON exists is skipped unless `from_stage` ≤ its number.
  - `cli.main()` argparse: `run <jd.md> [--budget 10] [--from-stage N] [--with-getleads] [--yes]`.
- Pre-run estimate: `max_pages * 0.10 + max_pages * 25 * 0.6 * 0.0064`, printed with the spec summary; abort if above budget; wait for Enter unless `--yes`.
- `fit_summary`: `"<top dim name> strong, <second dim name> <strong|partial>"` built from the two highest scores, no model call.

- [ ] **Step 1: Failing test**

```python
def test_pipeline_end_to_end_with_fakes(tmp_path, monkeypatch):
    # fake treg.call serving leads fixtures + profile fixtures, fake typesafe post serving fixture
    out = pipeline.run(jd_fixture, budget_usd=10, from_stage=1, with_getleads=False)
    rows = list(csv.DictReader(open(out)))
    assert rows[0]["tier"] == "Good Fit" and set(rows[0]) >= {"linkedin_url","stack_years","fit_summary"}
    assert (out.parent / "report.md").exists()
def test_rerun_skips_cached_stages(...):  # second run makes zero treg calls
```

- [ ] **Step 2: Run, confirm fail. Step 3: Implement.** Failed gate → row with tier Not a Fit, `gate_notes` = failed gate names and values, no Jev call. Unverified → proceeds to Jev, `gate_notes` lists unverified gates. Profile missing → row with tier Not a Fit, `gate_notes` = `profile_missing`.

- [ ] **Step 4: Run all tests, confirm pass.** `uv run pytest -q`

- [ ] **Step 5: Live run on the Oracle JD**

Precondition: `TYPESAFE_API_KEY` present in `.env` (Uday adds it). Run:
`uv run jd2candidates run tests/fixtures/jd_oracle.md --budget 6`
Expected: estimate printed and under 6, CSV at `runs/oracle-c2m-tech-lead-india/candidates.csv`, report with per-stage cost. Record actual cost and tier counts in the report; do not re-roll.

- [ ] **Step 6: Commit.** `git commit -am "feat: pipeline, CLI, CSV and report; first live run"`

---

### Task 8: GetLeads as a pluggable discovery source, free count in every estimate

**Files:**
- Modify: `jd2candidates/discover.py`, `jd2candidates/pipeline.py`, `jd2candidates/cli.py`
- Test: `tests/test_discover.py`

**Interfaces:**
- CLI gains `--source harvest|getleads` (default `harvest`), replacing `--with-getleads`.
- Produces:
  - `discover.getleads_count(spec: dict, api_key: str, post=urllib_post) -> int` calling the free GetLeads count endpoint with `linkedin_headline` = ",".join(stack_terms) and `countries` = [country name]. Used by the pre-run estimate whenever `GETLEADS_API_KEY` is set, regardless of source, printed as "GetLeads pool: N (N credits to pull)".
  - `discover.getleads(spec: dict, api_key: str, post=urllib_post) -> list[dict]` calling GetLeads REST contact search with the same filters, `limit` 100, paging by `offset` while `has_more`; rows mapped to the candidate shape with `source: "getleads"`. Used as the only discovery source when `--source getleads`.
- Both sources feed the same Task 4 profile step; GetLeads rows carry no dated experience, so gates still need the full profile.

- [ ] **Step 1: Failing tests.** `test_getleads_maps_rows`, `test_source_flag_selects_getleads`, `test_count_skipped_without_key`.
- [ ] **Step 2: Implement.** Confirm the REST paths (`/api/v1/contacts/count`, `/api/v1/contacts/search`) and auth header from the GetLeads API docs before coding. For `--source getleads`, print count and credit cost, then wait for Enter unless `--yes`; a `credits_exhausted` response stops cleanly with the upgrade message.
- [ ] **Step 3: Run, confirm pass. Commit.** `git commit -am "feat: GetLeads discovery source and free pool count"`

Note: last on purpose. Tasks 1 to 7 are complete without it. Flip the default to `getleads` once Uday puts credits on the plan.
