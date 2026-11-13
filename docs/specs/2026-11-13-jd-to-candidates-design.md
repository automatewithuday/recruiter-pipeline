# JD → Tiered Candidate List: design

Date: 2026-11-13. Status: approved by Uday 2026-11-13.

## Intent

A local pipeline that takes a job description and returns a tiered,
evidence-backed list of LinkedIn candidates ready for outreach. Martechs
pitches it to recruitment agencies as a replacement for LinkedIn Recruiter
seats plus the manual work of writing boolean strings and vetting profiles
by hand. The pitch is speed to a qualified shortlist and consistent
screening against the JD.

## Goals

- One command per JD: `uv run jd2candidates run <jd.md>` writes a CSV and a
  short run report.
- Every candidate in the output has had their full LinkedIn profile read
  (experience with dates, skills, about), not just a headline.
- Hard requirements from the JD (location, years in the core stack) are
  checked in code from profile data, never by a model.
- Soft fit is scored per JD dimension by Jev and combined in code into
  three tiers: Good Fit, Possible Fit, Not a Fit, with the evidence behind
  each score kept in the row.
- Cost per JD under about $10 at a few hundred profiles read.
- Modules are plain Python with no framework coupling, so the same code can
  later be wrapped as a Deepline Play.

## Non-goals

- No outreach. Output is a list; messaging stays with the agency.
- No email or phone discovery. LinkedIn URL is the contact handle.
- No UI, scheduling, or multi-tenant config. One JD, one run, one CSV.
- No Firecrawl. Uday removed it; treg and GetLeads cover discovery and
  profiles.
- No résumé parsing or ATS integration.

## Anti-goals

- A list where the tiering can't be explained. Every tier must trace to a
  gate result or a Jev score with the profile text it judged.
- Relaxing a hard gate to hit a count. Shortfalls are reported, not hidden.
- Duplicate enrichment. A profile is fetched once, from one provider.

## Constraints found during recon

| Item | State today | Effect |
|---|---|---|
| treg prepaid balance | $0.83 | Needs a top-up before a real run. ~$5 per JD. |
| GetLeads plan | Free, 6 credits. Counts are free, each returned contact is 1 credit. | GetLeads is a size-the-pool tool and an optional second source, not the main search, until the plan changes. |
| TypeSafe (Jev) key | Not in environment | Needed before the tiering stage runs. |
| HarvestAPI lead search | $0.05 to $0.10 per page of 25, supports LinkedIn boolean operators, title, location, years-of-experience and seniority filters, excludes. Pages repeat rows (about 60% unique). | Primary discovery. Dedupe by LinkedIn id. |
| HarvestAPI full profile | $0.0064 per call, 94.8% hit rate, returns experience with start and end dates, skills, about. | Single source for profile reads. |
| Apollo people search via treg | Free, title and location only, masked surnames, no profile URL without a paid match. | Not used. Lead search already returns URLs. |

## Approaches considered

1. **Local Python pipeline, treg plus GetLeads (chosen).** Fastest to a
   demo, cheapest per JD, everything runs from Uday's machine, modules reusable.
2. **Deepline Play.** Productized version with a warehouse and scheduled
   reruns. More setup before a first demo; comes after an agency says yes.
3. **n8n form for agencies.** Self-serve, most infrastructure, n8n connector
   not authorized here. Deferred.

Uday chose 1 and asked that it stay lean with no duplicated effort across
providers.

## Pipeline

Six modules under `jd2candidates/`, each a function that takes and returns
plain dicts or lists, with a JSON cache per stage in `runs/<slug>/` so a
rerun skips paid calls already made.

### 1. `criteria.py`: JD → search spec

Claude (Sonnet, through `claude -p`) reads the JD once and returns a JSON
spec:

- `hard`: country, min total years, min years in core stack, core stack
  terms with synonyms (e.g. CC&B, CCB, Customer Care and Billing).
- `soft`: 5 to 8 scoring dimensions, each with a one-line definition and
  what strong, partial, and absent evidence looks like.
- `search`: current-title list, boolean keyword string in LinkedIn
  operator syntax, exclude-title list (tester, recruiter, intern, student,
  trainer), seniority band.

The spec is written to `runs/<slug>/spec.json` and shown to the user
before any paid call. The user can edit it and rerun from stage 2.

### 2. `discover.py`: spec → candidate URLs

Primary: `harvestapi.linkedin.leads.search` through treg with `search`
(boolean string), `currentJobTitles`, `locations`, `yearsOfExperienceIds`,
`excludeCurrentJobTitles`. Page until a page adds fewer than 3 new ids or
the page cap in the spec is hit (default 20 pages, about $1 to $2).

Discovery source is pluggable via `--source harvest|getleads`. GetLeads
search with `linkedin_headline`, `skills`, and `countries` returns the whole
pool with deterministic filters, but each row costs 1 credit and the plan
is free today, so `harvest` is the default. The free GetLeads count runs in
every pre-run estimate when a key is present, so the pool size is always
visible. Flip the default to `getleads` once the plan has credits. Either
source feeds the same profile step; GetLeads rows carry no dated
experience, so the gates still need the full profile.

Output: deduped list of `{linkedin_url, name, headline, location, source}`.

The pipeline never widens the search on its own. If the pool is small or
most people fail the gates, the run report says so with the numbers, and
Uday decides whether to edit the spec and rerun. Automatic loosening would
break the "never relax a hard gate" rule.

### 3. `profile.py`: URL → full profile

`harvestapi.linkedin.user.profile` through treg, one call per URL, 5 in
flight (HarvestAPI starter concurrency). Response trimmed to the fields the
later stages need: name, headline, location, about, experience (title,
company, start, end, description, skills), skills, certifications. Raw
response kept in the cache; trimmed version used downstream.

### 4. `gate.py`: hard requirements in code

- Country from `location.parsed.countryCode` must match `hard.country`.
- Total years = span from earliest experience start to today.
- Stack years = sum of months across experience entries whose title or
  description matches any core stack synonym, overlapping ranges merged.
- Current role must not match an exclude title.

Each gate writes one of three results plus the number it computed:

- `pass`: data present and meets the bar.
- `fail`: data present and below the bar. Person goes to Not a Fit with
  the reason, Jev is skipped for them.
- `unverified`: data missing or unusable (no country code, no start date,
  no experience entries). Person continues to Jev and is exported with the
  gate name in `gate_notes`, so sparse profiles are flagged rather than
  silently rejected.

Date handling: a role with no end date is current. Month missing means
January for a start and December for an end. Overlapping stack roles are
merged before summing so parallel titles don't double count. Stack match is
case-insensitive on title plus description against the synonym list; no
fuzzy matching.

### 5. `tier.py`: Jev scores → tier

For each person who passed the gates, one Jev request carrying all soft
dimensions as Score questions, with state = the trimmed profile. TypeSafe
batches questions in one call, so this is one request per profile, about
300 per JD. Each Score has three levels in order: absent (0), partial (1),
strong (2). Jev returns a position between 0 and 2 plus a confidence value
between 0 and 1.

Combination in code, thresholds in `spec.json`:

- Haiku marks each dimension `must_have: true/false` in the spec when it
  writes it, and Uday confirms that along with the rest of the spec before
  any paid call.
- Good Fit: every must-have scores at least 1.2 and the mean over all
  dimensions is at least 1.1.
- Possible Fit: every must-have scores at least 0.5.
- Not a Fit: otherwise.

Uday asked for relaxed thresholds for the first few runs. The numbers above
are those. Tighten toward 1.5 / 1.4 / 0.7 once a few outputs have been
reviewed against real agency feedback.
- Any dimension with confidence below 0.5 is listed in `review_notes` so
  the agency knows which judgment to check by hand. It does not change the
  tier.

These numbers are proposals for Uday to confirm or change (see "Decided by
Uday"). They live in the spec so each JD can carry its own.

### 6. `export.py`: CSV and run report

CSV columns: `tier`, `full_name`, `current_title`, `company`, `location`,
`linkedin_url`, `total_years`, `stack_years`, one column per soft dimension
score, `gate_notes`, `review_notes`, `fit_summary` (one sentence assembled from
the top two dimension scores, no model call), `source`.

All rows are exported, sorted Good Fit, Possible Fit, Not a Fit, then by
mean score. The agency gets the audit trail; filtering to Good Fit is one
spreadsheet filter away. A `--good-only` flag is not built until asked.

Run report: pool found, profiles read, gate pass rate, tier counts, cost
per stage from treg's reported charges, and anything that could not be
checked.

## Spend control

- `--budget <usd>`, default 10. Before the first paid call the run prints
  the estimate (pages × page price, expected profiles × profile price) and
  stops if the estimate exceeds the budget.
- During the run, treg's reported charge per call is summed. When the sum
  reaches the budget, the run stops cleanly, writes what it has to the
  cache and report, and says how to resume. It never retries past a funds
  error.
- Resume is the same command. Cached stages are skipped, so a stopped run
  costs nothing to pick up after a top-up.

## Keys

Only `TYPESAFE_API_KEY` lives in `.env` in this folder, plus
`GETLEADS_API_KEY` when `--with-getleads` is used. treg calls go through
the installed `treg` CLI, which is already authenticated and injects the
provider key server-side. Haiku runs through `claude -p --model haiku`,
which uses Uday's Claude subscription, so no Anthropic API key is needed.
Nothing from `.env` is printed or logged.

## Cost per JD, estimated

| Stage | Volume | Cost |
|---|---|---|
| Criteria | 1 Haiku call | under $0.01 |
| Lead search | 20 pages | $1 to $2 |
| Full profiles | 300 | about $2 |
| Jev | 300 requests, 6 questions each | Pricing not in the public docs; confirm at signup |
| Total | | about $5 |

## Decided by Uday

- Local pipeline, not a Play or n8n, for now.
- Firecrawl removed from the pipeline.
- treg and GetLeads are the providers.
- Jev does the tiering into Good Fit / Possible Fit / Not a Fit.
- Lean: no provider does the same job twice.
- Tier thresholds: relaxed for the first runs (Good Fit = must-haves ≥ 1.2
  and mean ≥ 1.1; Possible Fit = must-haves ≥ 0.5). Haiku proposes
  must-have flags, Uday confirms per JD. Approved 2026-11-13.
- treg topped up by $10 on 2026-11-13. TypeSafe key to be added to `.env`
  by Uday.

## My calls (correct any of these)

- Unverified gate data flags the person rather than failing them.
- Per-run budget flag, default $10, with a pre-run estimate and a clean
  stop at the cap.
- Report-only on small pools; no automatic search widening.
- All rows exported with tier first, no good-only flag yet.
- One Jev request per profile with all dimensions batched.
- Confidence under 0.5 is a review note, not a tier change.

- HarvestAPI lead search is the only default discovery source. GetLeads is
  opt-in because the free plan can't return rows.
- Hard gates are computed from profile dates in code, not asked of Jev.
- Haiku writes the search spec; the user sees it before money is spent.
- Three tiers only. A fourth "Reach out anyway" tier adds noise.
- CSV plus a markdown run report. No Google Sheet until an agency asks.
- Per-stage JSON cache so a rerun after editing the spec or thresholds
  costs nothing for profiles already fetched.

## Left to the builder

- Exact HarvestAPI id values for years-of-experience and seniority bands
  (documented in the HarvestAPI SDK README).
- Jev question wording and the Score level texts, following the TypeSafe
  docs on Score and state.
- Rate limiting and retry around treg calls.
- The one self-check per non-trivial module (gate math on a fixture
  profile, tier combination on fixture scores).

## First test case

The Oracle Utilities C2M Technical Lead JD, India. Expected hard gates:
country IN, 10+ total years, 8+ years across C2M, CC&B, MDM, OUAF roles.
Expected soft dimensions: hands-on OUAF components, integrations, end-to-end
implementations, team leadership, client-facing work, utility domain
knowledge.
