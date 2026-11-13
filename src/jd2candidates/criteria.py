"""Stage 1: JD text -> search spec, written by Sonnet through `claude -p`, validated here."""
import json
import re
import subprocess
from pathlib import Path

from . import treg

THRESHOLDS = {"good_must_have_min": 1.2, "good_mean_min": 1.1, "possible_must_have_min": 0.5, "low_confidence": 0.5}
_PROMPT = Path(__file__).parent / "prompts" / "criteria.md"
_FENCE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.S)


class SpecError(ValueError):
    pass


def _req(d: dict, path: str):
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise SpecError(f"missing: {path}")
        cur = cur[part]
    return cur


def validate_spec(spec: dict) -> None:
    for p in ("slug", "hard.country_code", "hard.country_name", "hard.min_total_years", "hard.min_stack_years",
              "hard.stack_terms", "search.boolean", "search.current_titles", "search.exclude_titles",
              "search.geo_ids", "search.years_of_experience_ids", "search.max_pages", "thresholds"):
        _req(spec, p)
    if len(_req(spec, "search.boolean")) > 300:
        raise SpecError("search.boolean over 300 chars (HarvestAPI limit)")
    if not _req(spec, "hard.country_code"):
        raise SpecError("missing: hard.country_code (JD states no location)")
    soft = _req(spec, "soft")
    if not isinstance(soft, list) or not soft:
        raise SpecError("missing: soft (need 1+ dimensions)")
    for i, d in enumerate(soft):
        for k in ("id", "name", "must_have", "levels"):
            if k not in d:
                raise SpecError(f"missing: soft[{i}].{k}")
        if len(d["levels"]) != 3:
            raise SpecError(f"missing: soft[{i}].levels must have exactly 3 entries")


def _extract_json(text: str) -> dict:
    m = _FENCE.search(text)
    body = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(body)


def jd_to_spec(jd_text: str) -> dict:
    prompt = _PROMPT.read_text() + "\n\nJOB DESCRIPTION:\n" + jd_text
    r = subprocess.run(["claude", "-p", "--model", "sonnet", "--output-format", "text"],
                       input=prompt, capture_output=True, text=True)
    if r.returncode != 0:
        raise SpecError(f"claude -p failed: {r.stderr.strip()[:300]}")
    spec = _extract_json(r.stdout)
    spec["thresholds"] = dict(THRESHOLDS)
    if not spec.get("search", {}).get("geo_ids"):
        name = spec.get("hard", {}).get("country_name") or ""
        if name:
            data, _ = treg.call("harvestapi.linkedin.geo.search", {"search": name})
            els = data.get("elements") or []
            spec["search"]["geo_ids"] = [els[0]["geoId"]] if els else []
    validate_spec(spec)
    return spec
