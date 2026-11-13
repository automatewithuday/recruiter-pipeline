"""Stage 6: CSV and run report."""
import csv
from pathlib import Path

TIER_ORDER = ["Good Fit", "Possible Fit", "Not a Fit"]
FIXED = ["tier", "full_name", "current_title", "company", "location", "linkedin_url", "total_years", "stack_years", "fit_reasoning", "ask_on_call"]
TAIL = ["gate_notes", "review_notes", "fit_summary", "source"]


def columns(soft: list[dict]) -> list[str]:
    return FIXED + [d["id"] for d in soft] + TAIL


def write_csv(rows: list[dict], soft: list[dict], path: Path) -> None:
    cols = columns(soft)
    rows = sorted(rows, key=lambda r: (TIER_ORDER.index(r["tier"]), -float(r.get("_mean") or 0)))
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


SHORTLIST = FIXED + ["gate_notes", "review_notes"]  # what a recruiter needs to pick up the phone; no per-dimension scores


def write_shortlist(rows: list[dict], path: Path) -> None:
    good = sorted((r for r in rows if r["tier"] == "Good Fit"), key=lambda r: -float(r.get("_mean") or 0))
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SHORTLIST, extrasaction="ignore")
        w.writeheader()
        w.writerows(good)


def write_report(stats: dict, path: Path) -> None:
    s = stats
    lines = [f"# Run report: {s['slug']}", "",
             f"- Pool found: {s['pool']} (pages {s['pages']}, skipped no-URL {s['skipped_no_url']})"]
    if s.get("angles"):
        lines += [f"  - {k}: {v}" for k, v in s["angles"].items()]
    lines += [
             f"- Profiles read: {s['profiles_read']}, missing: {s['profiles_missing']}",
             f"- Gates: pass {s['gate_pass']}, fail {s['gate_fail']}, flagged and scored (unverified or below bar) {s['gate_flagged']}",
             f"- Jev scored: {s['scored']}, failed: {s['jev_failed']}",
             f"- Recruiter notes: written {s['notes_written']}, missing {s['notes_missing']}", "",
             "## Tiers", ""] + [f"- {t}: {s['tiers'].get(t, 0)}" for t in TIER_ORDER] + ["", "## Cost (USD)", ""] + \
            [f"- {k}: {v:.4f}" for k, v in s["cost"].items()] + [f"- total: {sum(s['cost'].values()):.4f} USD"]
    if s.get("stopped"):
        lines += ["", f"Stopped early: {s['stopped']}. Rerun the same command to resume from cache."]
    path.write_text("\n".join(lines) + "\n")
