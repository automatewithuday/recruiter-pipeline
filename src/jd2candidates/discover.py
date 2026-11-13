"""Stage 2: spec -> candidate URLs via HarvestAPI lead search (through treg), from four search angles."""
from . import treg
from .budget import Budget, BudgetExceeded

LEADS = "harvestapi.linkedin.leads.search"
MIN_NEW_PER_PAGE = 3
KEYWORD_ONLY_PAGES = 4  # ponytail: without a title filter the keyword matches thousands; only the top-ranked pages are worth reading


def _row(el: dict, source: str) -> dict:
    pos = (el.get("currentPositions") or [{}])[0]
    return {
        "linkedin_url": el["linkedinUrl"],
        "name": " ".join(x for x in (el.get("firstName"), el.get("lastName")) if x),
        "headline": pos.get("title") or el.get("summary") or "",
        "location": (el.get("location") or {}).get("linkedinText") or "",
        "source": source,
    }


def angles(spec: dict) -> list[tuple[str, dict, int]]:
    """(source tag, filters, page cap). Measured on the Oracle C2M run: titles that name the stack, past titles that name it,
    and the bare keyword each found Good Fits the keyword+generic-title search missed."""
    s = spec["search"]
    kw, n = s["boolean"], int(s["max_pages"])
    stack = ",".join(s.get("stack_titles") or [])
    out = [("harvest_leads", {"search": kw, "currentJobTitles": ",".join(s["current_titles"])}, n)]
    if stack:
        out += [("harvest_leads:title_names_stack", {"currentJobTitles": stack}, n),
                ("harvest_leads:past_title_names_stack", {"pastJobTitles": stack}, n)]
    out.append(("harvest_leads:keyword_no_title_filter", {"search": kw}, min(n, KEYWORD_ONLY_PAGES)))
    return out


def discover(spec: dict, budget: Budget, call=treg.call) -> dict:
    s = spec["search"]
    base = {
        "geoIds": ",".join(str(g) for g in s["geo_ids"]),
        "yearsOfExperienceIds": ",".join(str(y) for y in s["years_of_experience_ids"]),
        "excludeCurrentJobTitles": ",".join(s["exclude_titles"]),
    }
    seen: dict[str, dict] = {}
    out = {"candidates": [], "pages": 0, "skipped_no_url": 0, "charged_usd": 0.0, "angles": {}}
    for source, extra, max_pages in angles(spec):
        found = 0
        for page in range(1, max_pages + 1):
            data, usd = call(LEADS, {**base, **extra, "page": str(page)})
            try:
                budget.add(usd)
            except BudgetExceeded:
                out["stopped"] = "budget"
                break
            out["charged_usd"] += usd
            out["pages"] += 1
            new = 0
            for el in data.get("elements") or []:
                url = el.get("linkedinUrl")
                if not url:
                    out["skipped_no_url"] += 1
                    continue
                if url not in seen:
                    seen[url] = _row(el, source)
                    new += 1
            found += new
            if new < MIN_NEW_PER_PAGE:
                break
        out["angles"][source] = found
        if out.get("stopped"):
            break
    out["candidates"] = list(seen.values())
    return out
