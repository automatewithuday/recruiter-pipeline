"""Stage 3: candidate URL -> trimmed full profile via HarvestAPI (through treg)."""
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import treg
from .budget import Budget, BudgetExceeded

PROFILE = "harvestapi.linkedin.user.profile"


def _date(d) -> dict | None:
    if not d or not d.get("year"):
        return None
    return {"year": d["year"], "month": d.get("month")}


def _names(items) -> list[str]:
    return [i["name"] for i in (items or []) if isinstance(i, dict) and i.get("name")]


def trim(raw: dict) -> dict | None:
    el = raw.get("element")
    if not el:
        return None
    loc = el.get("location") or {}
    return {
        "linkedin_url": el.get("linkedinUrl"),
        "full_name": " ".join(x for x in (el.get("firstName"), el.get("lastName")) if x),
        "headline": el.get("headline") or "",
        "location_text": loc.get("linkedinText") or "",
        "country_code": loc.get("countryCode"),
        "about": el.get("about") or "",
        "skills": _names(el.get("skills")),
        "certifications": _names(el.get("certifications")),
        "experience": [
            {
                "title": e.get("position") or "",
                "company": e.get("companyName") or "",
                "description": e.get("description") or "",
                "skills": _names(e.get("skills")),
                "start": _date(e.get("startDate")),
                "end": _date(e.get("endDate")),
            }
            for e in (el.get("experience") or [])
        ],
    }


def fetch_profiles(candidates: list[dict], budget: Budget, call=treg.call, workers: int = 5) -> dict:
    out = {"profiles": [], "missing": [], "charged_usd": 0.0}
    by_url = {c["linkedin_url"]: c for c in candidates}
    got: dict[str, dict] = {}

    def one(url: str):
        data, usd = call(PROFILE, {"url": url})
        budget.add(usd)  # raises BudgetExceeded; charged anyway, so count it below
        return url, data, usd

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(one, url): url for url in by_url}
        for f in as_completed(futures):
            try:
                url, data, usd = f.result()
            except BudgetExceeded:
                out["stopped"] = "budget"
                for pf in futures:
                    pf.cancel()
                continue
            out["charged_usd"] += usd
            t = trim(data)
            if t is None:
                out["missing"].append(url)
            else:
                t["source"] = by_url[url].get("source", "")
                t["linkedin_url"] = t["linkedin_url"] or url
                got[url] = t
    out["profiles"] = [got[u] for u in by_url if u in got]
    return out
