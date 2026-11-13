# recruiter-pipeline (jd2candidates)

Job description in, tiered LinkedIn candidate shortlist out. Built for niche technical roles where a recruiter would otherwise hand-stitch boolean searches and read hundreds of profiles.

Pipeline: JD → search spec (Sonnet) → LinkedIn lead search from four angles (HarvestAPI via treg, optional GetLeads) → full profiles → hard gates computed from dated roles → Jev scoring per JD dimension → tier → recruiter notes (Haiku) → CSV.

## Run

```bash
uv sync
uv run jd2candidates run path/to/jd.md --budget 6          # HarvestAPI only
uv run jd2candidates run path/to/jd.md --budget 6 --source both   # plus GetLeads, deduped
```

Outputs in `runs/<slug>/`: `shortlist.csv` (Good Fits, recruiter columns), `candidates.csv` (everyone, with scores), `report.md`. Every stage is cached there; rerunning only pays for missing stages. `--from-stage N` recomputes from stage N.

## Needs

- `treg` CLI authenticated (HarvestAPI access is injected server-side).
- `claude` CLI logged in (Sonnet for the spec, Haiku for notes).
- `.env`: `TYPESAFE_API_KEY` (Jev scoring), `GETLEADS_API_KEY` (optional second source; counts are free, rows cost 1 credit).

## Cost (measured, Nov 2026)

About $0.0064 per profile searched and read, almost all of it HarvestAPI data; the model stages are under 1% of the bill. Roughly $32 per 5,000 profiles.

## Rules the output follows

Hard gates come from dated roles, not keywords: total years, stack years, country, excluded titles. Near misses (5–8 stack years, stack named only in the headline, more years than the JD range) are flagged and scored, not rejected, and each flag adds a screening question. Titles above the role's level are excluded. Tiers and thresholds live in the spec and are the operator's to tune.

Design: `docs/specs/`. Tests: `uv run pytest -q`.
