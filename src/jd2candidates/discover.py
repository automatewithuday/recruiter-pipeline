"""Stage 2: spec -> candidate URLs via HarvestAPI lead search (through treg)."""
from . import treg
from .budget import Budget, BudgetExceeded

LEADS = "harvestapi.linkedin.leads.search"
MIN_NEW_PER_PAGE = 3


def _row(el: dict) -> dict:
    pos = (el.get("currentPositions") or [{}])[0]
    return {
        "linkedin_url": el["linkedinUrl"],
        "name": " ".join(x for x in (el.get("firstName"), el.get("lastName")) if x),
        "headline": pos.get("title") or el.get("summary") or "",
        "location": (el.get("location") or {}).get("linkedinText") or "",
        "source": "harvest_leads",
    }


def discover(spec: dict, budget: Budget, call=treg.call) -> dict:
    s = spec["search"]
    base = {
        "search": s["boolean"],
        "currentJobTitles": ",".join(s["current_titles"]),
        "geoIds": ",".join(str(g) for g in s["geo_ids"]),
        "yearsOfExperienceIds": ",".join(str(y) for y in s["years_of_experience_ids"]),
        "excludeCurrentJobTitles": ",".join(s["exclude_titles"]),
    }
    seen: dict[str, dict] = {}
    out = {"candidates": [], "pages": 0, "skipped_no_url": 0, "charged_usd": 0.0}
    for page in range(1, int(s["max_pages"]) + 1):
        data, usd = call(LEADS, {**base, "page": str(page)})
        try:
            budget.add(usd)
        except BudgetExceeded:
            out["stopped"] = "budget"
            break
        out["charged_usd"] += usd
        out["pages"] = page
        new = 0
        for el in data.get("elements") or []:
            url = el.get("linkedinUrl")
            if not url:
                out["skipped_no_url"] += 1
                continue
            if url not in seen:
                seen[url] = _row(el)
                new += 1
        if new < MIN_NEW_PER_PAGE:
            break
    out["candidates"] = list(seen.values())
    return out
