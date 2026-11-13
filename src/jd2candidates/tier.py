"""Stage 5: Jev scores per soft dimension (one request per profile), tier assignment in code."""
from datetime import date

from . import gate, typesafe


def build_questions(soft: list[dict]) -> dict:
    return {d["id"]: {"type": "score",
                      "instructions": f"How strongly does this candidate's profile show: {d['name']}?",
                      "criteria": list(d["levels"])} for d in soft}


def _state(profile: dict, today: date) -> dict:
    exp = []
    for e in profile.get("experience", []):
        yrs = round(gate.months(e["start"], e["end"], today) / 12, 1) if e.get("start") else None
        exp.append({"title": e.get("title", ""), "company": e.get("company", ""),
                    "description": e.get("description", ""), "skills": e.get("skills", []), "years": yrs})
    return {"headline": profile.get("headline", ""), "about": profile.get("about", ""),
            "skills": profile.get("skills", []), "certifications": profile.get("certifications", []), "experience": exp}


def score_profile(profile: dict, spec: dict, api_key: str, post=typesafe.urllib_post, today: date | None = None) -> dict:
    try:
        resp = typesafe.system_one(_state(profile, today or date.today()), build_questions(spec["soft"]), api_key, post=post)
    except typesafe.TypeSafeError:
        return {"error": "jev_failed"}
    answers = resp.get("answers") or {}
    return {d["id"]: {"score": float(answers[d["id"]]["score"]), "confidence": float(answers[d["id"]].get("confidence", 1.0))}
            for d in spec["soft"] if d["id"] in answers}


def assign(scores: dict, spec: dict) -> dict:
    th = spec["thresholds"]
    must = [d["id"] for d in spec["soft"] if d["must_have"]]
    vals = [scores[d["id"]]["score"] for d in spec["soft"] if d["id"] in scores]
    mean = sum(vals) / len(vals) if vals else 0.0
    must_min = min((scores[m]["score"] for m in must if m in scores), default=2.0)
    if must_min >= th["good_must_have_min"] and mean >= th["good_mean_min"]:
        t = "Good Fit"
    elif must_min >= th["possible_must_have_min"]:
        t = "Possible Fit"
    else:
        t = "Not a Fit"
    notes = [d["id"] for d in spec["soft"] if d["id"] in scores and scores[d["id"]]["confidence"] < th["low_confidence"]]
    return {"tier": t, "mean": round(mean, 3), "review_notes": notes}
