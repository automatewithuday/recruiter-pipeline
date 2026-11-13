"""Orchestrates the six stages with a per-run cache. Stage numbers: 1 spec, 2 discover, 3 profiles, 4 gates, 5 scores, 6 notes, then export."""
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from . import criteria, discover, env, export, gate, notes, profile, tier, treg, typesafe
from .budget import Budget
from .cache import RunDir

_call = treg.call
_post = typesafe.urllib_post
_ask = notes.ask
PAGE_USD, PROFILE_USD, ROWS_PER_PAGE, UNIQUE_RATE = 0.10, 0.0064, 25, 0.6


def estimate(spec: dict) -> float:
    pages = int(spec["search"]["max_pages"])
    return pages * PAGE_USD + pages * ROWS_PER_PAGE * UNIQUE_RATE * PROFILE_USD


def _confirm(msg: str, yes: bool) -> None:
    print(msg)
    if not yes:
        input("Press Enter to continue, Ctrl-C to abort... ")


def _summary(spec: dict) -> str:
    must = [d["id"] for d in spec["soft"] if d["must_have"]]
    return (f"Spec {spec['slug']}: country {spec['hard']['country_code']}, total>={spec['hard']['min_total_years']}y, "
            f"stack>={spec['hard']['min_stack_years']}y\n  boolean: {spec['search']['boolean']}\n"
            f"  titles: {', '.join(spec['search']['current_titles'])}\n  must-have: {', '.join(must)}")


def _row(cand: dict, prof: dict | None, g: dict | None, scores: dict | None, verdict: dict | None, spec: dict) -> dict:
    r = {"tier": "Not a Fit", "full_name": cand.get("name", ""), "current_title": cand.get("headline", ""), "company": "",
         "location": cand.get("location", ""), "linkedin_url": cand["linkedin_url"], "total_years": "", "stack_years": "",
         "gate_notes": "", "review_notes": "", "fit_summary": "", "source": cand.get("source", ""), "_mean": 0.0}
    if prof is None:
        r["gate_notes"] = "profile_missing"
        return r
    cur = next((e for e in prof["experience"] if e.get("end") is None), None) or {}
    r.update(full_name=prof["full_name"] or r["full_name"], current_title=cur.get("title") or prof["headline"],
             company=cur.get("company", ""), location=prof["location_text"] or r["location"], linkedin_url=prof["linkedin_url"])
    r["total_years"] = g["total_years"]["value"] if g["total_years"]["value"] is not None else ""
    r["stack_years"] = g["stack_years"]["value"] if g["stack_years"]["value"] is not None else ""
    notes = [f"{k}={v['value']} {v['result']}" for k, v in g.items() if k != "passed" and v["result"] != "pass"]
    r["gate_notes"] = "; ".join(notes)
    if not g["passed"]:
        return r
    if not scores or "error" in scores:
        r["gate_notes"] = "; ".join(filter(None, [r["gate_notes"], "jev_failed"]))
        r["tier"] = "Possible Fit"
        return r
    for d in spec["soft"]:
        r[d["id"]] = scores.get(d["id"], {}).get("score", "")
    r["tier"], r["_mean"] = verdict["tier"], verdict["mean"]
    r["review_notes"] = ", ".join(verdict["review_notes"])
    names = {d["id"]: d["name"] for d in spec["soft"]}
    top = sorted(((v["score"], k) for k, v in scores.items()), reverse=True)[:2]
    word = lambda s: "strong" if s >= 1.5 else "partial" if s >= 0.75 else "weak"
    r["fit_summary"] = ", ".join(f"{names[k]} {word(s)}" for s, k in top)
    return r


def run(jd_path: Path, budget_usd: float = 10.0, from_stage: int = 0, source: str = "harvest", yes: bool = False) -> Path:
    env.load()
    jd = Path(jd_path).read_text()
    spec_cache = RunDir("_specs")  # slug unknown until stage 1, so cache the spec by JD hash
    import hashlib
    h = hashlib.sha1(jd.encode()).hexdigest()[:10]
    redo = lambda stage: 0 < from_stage <= stage  # --from-stage N recomputes stage N onward
    cached = spec_cache.read(f"spec-{h}")
    if cached and not redo(1):
        spec = cached
    else:
        spec = criteria.jd_to_spec(jd)
        spec_cache.write(f"spec-{h}", spec)
    rd = RunDir(spec["slug"])
    rd.write("spec", spec)
    budget = Budget(budget_usd)
    cost: dict[str, float] = {}
    stopped = None

    cands = None if redo(2) else rd.read("candidates")
    if cands is None:
        est = estimate(spec)
        msg = f"{_summary(spec)}\n\nPre-run estimate: {est:.2f} USD (budget {budget_usd:.2f})"
        if est > budget_usd:
            print(msg + "\nEstimate exceeds budget; lower max_pages in the spec or raise --budget.")
            sys.exit(1)
        _confirm(msg, yes)
        d = discover.discover(spec, budget, call=_call)
        cost["discover"] = d["charged_usd"]
        stopped = d.get("stopped")
        cands = d["candidates"]
        rd.write("candidates", cands)
        rd.write("discover_stats", {k: v for k, v in d.items() if k != "candidates"})
    dstats = rd.read("discover_stats") or {}

    profs = None if redo(3) else rd.read("profiles")
    if profs is None:
        p = profile.fetch_profiles(cands, budget, call=_call)
        cost["profiles"] = p["charged_usd"]
        stopped = stopped or p.get("stopped")
        profs = {"profiles": p["profiles"], "missing": p["missing"]}
        rd.write("profiles", profs)
    by_url = {pr["linkedin_url"]: pr for pr in profs["profiles"]}
    req_url = {}
    for c in cands:  # map requested url -> profile (HarvestAPI may canonicalise)
        req_url[c["linkedin_url"]] = by_url.get(c["linkedin_url"])
    unmatched = [pr for pr in profs["profiles"] if pr["linkedin_url"] not in req_url]
    for c in cands:
        if req_url[c["linkedin_url"]] is None and unmatched:
            req_url[c["linkedin_url"]] = unmatched.pop(0)

    today = date.today()
    gates = {u: gate.apply(pr, spec["hard"], today, exclude_titles=spec["search"]["exclude_titles"]) for u, pr in req_url.items() if pr}
    rd.write("gates", gates)

    scores = None if redo(5) else rd.read("scores")
    if scores is None:
        scores = {}
    todo = [u for u, g in gates.items() if g["passed"] and u not in scores]
    if todo:
        key = os.environ.get("TYPESAFE_API_KEY", "")
        if not key:
            print("TYPESAFE_API_KEY missing in .env; cannot score. Gates and export still run.")
        else:
            with ThreadPoolExecutor(max_workers=4) as ex:
                for u, s in zip(todo, ex.map(lambda u: tier.score_profile(req_url[u], spec, key, post=_post, today=today), todo)):
                    scores[u] = s
            rd.write("scores", scores)

    rows, tiers, jev_failed = [], {}, 0
    for c in cands:
        u = c["linkedin_url"]; pr = req_url.get(u); g = gates.get(u); sc = scores.get(u)
        verdict = tier.assign(sc, spec) if sc and "error" not in sc else None
        if sc and "error" in sc:
            jev_failed += 1
        r = _row(c, pr, g, sc, verdict, spec)
        tiers[r["tier"]] = tiers.get(r["tier"], 0) + 1
        rows.append(r)
    urls = [c["linkedin_url"] for c in cands]
    notes_c = (None if redo(6) else rd.read("notes")) or {}
    fit = {u: r for u, r in zip(urls, rows) if r["tier"] != "Not a Fit" and scores.get(u) and "error" not in scores[u]}
    need = {u: notes.entry(r, req_url[u], scores[u], spec, today) for u, r in fit.items()
            if notes_c.get(u, {}).get("tier") != r["tier"]}  # a tier change makes the old reasoning stale
    if need:
        notes_c.update(notes.write(need, spec, ask=_ask))
        rd.write("notes", notes_c)
    for u, r in fit.items():
        n = notes_c.get(u)
        if n and n["tier"] == r["tier"]:
            r["fit_reasoning"] = n["reasoning"]
            r["ask_on_call"] = "\n".join(f"{i}. {q}" for i, q in enumerate(n["ask_on_call"], 1))
    out = rd.path / "candidates.csv"
    export.write_csv(rows, spec["soft"], out)
    export.write_report({
        "slug": spec["slug"], "pool": len(cands), "pages": dstats.get("pages", "?"), "skipped_no_url": dstats.get("skipped_no_url", "?"),
        "profiles_read": len(profs["profiles"]), "profiles_missing": len(profs["missing"]),
        "gate_pass": sum(1 for g in gates.values() if g["passed"] and all(v["result"] == "pass" for k, v in g.items() if k != "passed")),
        "gate_fail": sum(1 for g in gates.values() if not g["passed"]),
        "gate_flagged": sum(1 for g in gates.values() if g["passed"] and any(v["result"] != "pass" for k, v in g.items() if k != "passed")),
        "notes_written": sum(1 for r in fit.values() if r.get("fit_reasoning")), "notes_missing": sum(1 for r in fit.values() if not r.get("fit_reasoning")),
        "scored": sum(1 for s in scores.values() if "error" not in s), "jev_failed": jev_failed,
        "tiers": tiers, "cost": cost or {"cached": 0.0}, "stopped": stopped,
    }, rd.path / "report.md")
    print(f"Wrote {out} and report.md. Tiers: {tiers}. Spent this run: {sum(cost.values()):.4f} USD")
    return out
