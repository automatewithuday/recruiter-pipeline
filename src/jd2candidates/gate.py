"""Stage 4: hard requirements computed from profile dates. Code only, no model."""
from datetime import date


def _start(d: dict) -> date:
    return date(d["year"], d.get("month") or 1, 1)


def _end(d: dict | None, today: date) -> date:
    if d is None:
        return today
    return date(d["year"], d.get("month") or 12, 1)


def months(start: dict, end: dict | None, today: date) -> int:
    s, e = _start(start), _end(end, today)
    return max(0, (e.year - s.year) * 12 + (e.month - s.month) + 1 - (1 if end is None else 0))


def merge_ranges(ranges: list[tuple[date, date]]) -> list[tuple[date, date]]:
    out: list[tuple[date, date]] = []
    for s, e in sorted(ranges):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def matches_stack(text: str, terms: list[str]) -> bool:
    t = text.lower()
    return any(term.lower() in t for term in terms)


def _years(ranges: list[tuple[date, date]]) -> float:
    return sum(((e.year - s.year) * 12 + (e.month - s.month)) for s, e in merge_ranges(ranges)) / 12


def apply(profile: dict, hard: dict, today: date, exclude_titles: list[str] | None = None) -> dict:
    R = lambda result, value=None: {"result": result, "value": value}
    g: dict = {}

    cc = profile.get("country_code")
    g["country"] = R("unverified") if not cc else R("pass" if cc.upper() == hard["country_code"].upper() else "fail", cc)

    dated = [e for e in profile.get("experience", []) if e.get("start")]
    if not dated:
        g["total_years"] = R("unverified")
        g["stack_years"] = R("unverified")
    else:
        all_r = [(_start(e["start"]), _end(e["end"], today)) for e in dated]
        total = round(_years([(min(s for s, _ in all_r), today)]), 1)
        g["total_years"] = R("pass" if total >= hard["min_total_years"] else "fail", total)
        stack_r = [(_start(e["start"]), _end(e["end"], today)) for e in dated
                   if matches_stack(f'{e.get("title","")} {e.get("description","")} {" ".join(e.get("skills") or [])}', hard["stack_terms"])]
        stack = round(_years(stack_r), 1) if stack_r else 0.0
        g["stack_years"] = R("pass" if stack >= hard["min_stack_years"] else "fail", stack)

    current = next((e for e in profile.get("experience", []) if e.get("end") is None), None)
    title = (current or {}).get("title", "")
    hit = next((x for x in (exclude_titles or []) if x.lower() in title.lower()), None)
    g["excluded_title"] = R("fail", title) if hit else R("pass", title)

    g["passed"] = all(v["result"] != "fail" for k, v in g.items() if k != "passed")
    return g
