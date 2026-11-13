"""Optional discovery source: GetLeads contact search. Count is free; each returned contact costs 1 plan credit."""
from .typesafe import HTTPStatus, urllib_post

BASE = "https://app.getleads.io/api/v1/contacts/search"
PAGE = 100
COLUMNS = ["full_name", "linkedin_url", "current_title", "linkedin_headline", "current_employer", "contact_location"]


def _filters(spec: dict) -> dict:
    return {"countries": [spec["hard"]["country_name"]],
            "linkedin_headline": ",".join(spec["hard"]["stack_terms"]),  # comma = OR, substring match
            "exclude_job_titles": list(spec["search"]["exclude_titles"])}


def count(spec: dict, api_key: str, post=urllib_post) -> int:
    return int(post(f"{BASE}/count", _filters(spec), {"X-API-Key": api_key}).get("total_matching", 0))


def _row(c: dict) -> dict:
    return {"linkedin_url": c["linkedin_url"], "name": c.get("full_name") or "", "headline": c.get("current_title") or c.get("linkedin_headline") or "",
            "location": c.get("contact_location") or "", "source": "getleads"}


def search(spec: dict, api_key: str, post=urllib_post) -> dict:
    out = {"candidates": [], "pages": 0, "skipped_no_url": 0, "charged_usd": 0.0, "credits_used": 0}
    seen: set[str] = set()
    offset = 0
    while True:
        try:
            resp = post(BASE, {**_filters(spec), "limit": PAGE, "offset": offset, "columns": COLUMNS}, {"X-API-Key": api_key})
        except HTTPStatus as e:
            if e.code == 402 or "credits_exhausted" in str(e):
                out["stopped"] = "credits"
                break
            raise
        out["pages"] += 1
        for c in resp.get("contacts") or []:
            out["credits_used"] += 1
            url = c.get("linkedin_url")
            if not url:
                out["skipped_no_url"] += 1
            elif url not in seen:
                seen.add(url)
                out["candidates"].append(_row(c))
        if resp.get("credits_exhausted"):
            out["stopped"] = "credits"
            break
        if not resp.get("has_more"):
            break
        offset = resp.get("next_offset", offset + PAGE)
    return out
