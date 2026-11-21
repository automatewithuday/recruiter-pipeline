# Recruiter Pipeline

**Give it a job description. Get back a shortlist of the people on LinkedIn who actually fit, with a note on each one explaining why and what to ask them on the first call.**

Built for the hard-to-fill technical roles where a recruiter would otherwise spend days writing boolean searches, paging through LinkedIn Recruiter, and reading hundreds of profiles one at a time.

---

## The problem it solves

For a niche role, say an Oracle Utilities C2M tech lead in India, the normal process looks like this:

1. Someone writes a boolean search, guessing at the keywords and title variations.
2. LinkedIn Recruiter returns a few thousand people.
3. A recruiter opens profiles one by one, checks years of experience, checks the right technology shows up in real jobs and not just the headline, and throws most of them out.
4. After a day or two there is a list of maybe ten names and a lot of tired eyes.

Most of that time goes into reading profiles that were never going to fit. This tool does the reading.

## What you do

Paste the job description into a text file. That is the only input.

## What you get back

A folder with three files:

| File | What it is | Who it's for |
|---|---|---|
| **shortlist.csv** | The Good Fits only. Name, current title, company, location, LinkedIn link, years of experience, years on the required stack, why they fit, and what to ask on the call. | The recruiter picking up the phone. |
| **candidates.csv** | Everyone found, sorted into Good Fit, Possible Fit and Not a Fit, with the reason for each. | Anyone who wants to check the work or dig into the Possible Fits. |
| **report.md** | A one-page summary: how many people were found, how many passed each check, what it cost. | The person who owns the search. |

Nobody is thrown away silently. Every Not a Fit has a plain-English reason, so you can audit the decision and overrule it if you disagree.

## How it works, in plain terms

The tool runs the same checks a good recruiter runs, in the same order, just on every profile instead of a sample.

**Step 1. Read the job description.**
An AI model reads the JD and writes down what the role actually needs: must-have requirements (years of experience, the core technology, location), nice-to-haves (the things that separate a good candidate from a great one), and the titles that are too senior to realistically move for this role. You can read and edit this list before anything else happens.

**Step 2. Find people on LinkedIn.**
The tool searches LinkedIn from several angles at once: people with the technology in their current title, people who had it in a past title, people with it in their headline, and plain keyword matches. This catches the people a single boolean search misses, because a C2M lead might be titled "Technical Lead", "Senior Consultant", "Solution Architect" or "Oracle Utilities Specialist" depending on the company.

**Step 3. Read every profile in full.**
Not the search snippet. The full profile, with every role and its dates.

**Step 4. Apply the hard requirements.**
From the dated job history, the tool works out total years of experience, how many of those years were actually spent on the required technology, and whether the person is in the right country. People above the role's level (directors, VPs, partners) are set aside, because they will not move for a hands-on role. This step is pure arithmetic on dates, no guessing.

Near misses are not rejected. Someone with slightly fewer stack years than asked, or with the technology mentioned only in their headline, is flagged, still scored, and given a specific question to ask on the call to confirm.

**Step 5. Score the people who passed.**
Everyone who cleared the hard requirements is scored against the nice-to-haves from the JD, one dimension at a time. The scores decide the tier: Good Fit, Possible Fit or Not a Fit. Flagged people are capped at Possible Fit until a recruiter has confirmed the open question.

**Step 6. Write the recruiter notes.**
For every Good and Possible Fit, a short note: why this person landed in this tier, and the one or two things worth asking on a first call.

## What it did on the first real run

Job: Oracle Utilities C2M Tech Lead, India.

| | |
|---|---|
| People found on LinkedIn | 783 |
| Profiles read in full | 783 |
| Failed a hard requirement | 485 |
| Passed clean | 58 |
| Passed with a flag, scored anyway | 240 |
| **Good Fit** | **8** |
| Possible Fit | 82 |
| Not a Fit | 693 |
| Cost | About $5 |

Eight names a recruiter can call today, each with a reason and a screening question, from a pool of 783 that would have taken days to read by hand.

## What it costs

Roughly $0.0064 per profile searched and read, so about $32 per 5,000 profiles. Almost all of that is the LinkedIn data itself. The AI parts are under one percent of the bill. You set a dollar cap per run and the search stops there.

## What it does not do

- It does not contact candidates. It produces a list; the outreach is yours.
- It does not replace a recruiter's judgment. It removes the reading, so the judgment goes on eight people instead of eight hundred.
- It does not log into anyone's LinkedIn account. It uses public profile data through a licensed data provider.

## The rules it follows

These are deliberate choices, written down so they can be argued with.

- Hard requirements are computed from dated roles, never from keywords alone.
- Near misses are flagged and scored, not dropped. Each flag adds a call question.
- Titles above the role's level are excluded. Those people will not move for it.
- Thresholds for each tier live in the spec file and belong to the person running the search, not the tool.
- One run reads the whole pool once and caches it. Rerunning with a tighter rule costs nothing.

---

## For the person running it

Technical setup, ignore this section if you are not the operator.

```bash
uv sync
uv run jd2candidates run path/to/jd.md --budget 6               # default source
uv run jd2candidates run path/to/jd.md --budget 6 --source both  # plus the second source, deduped by LinkedIn URL
```

Outputs land in `runs/<slug>/`. Every stage is cached there; rerunning only pays for missing stages. `--from-stage N` recomputes from stage N onward.

Needs:

- `treg` CLI authenticated (HarvestAPI access is injected server-side).
- `claude` CLI logged in (Sonnet writes the spec, Haiku writes the notes).
- `.env` with `TYPESAFE_API_KEY` (Jev scoring) and optionally `GETLEADS_API_KEY` (second discovery source; counts are free, rows cost 1 credit).

Design notes: `docs/specs/`. Tests: `uv run pytest -q`.
