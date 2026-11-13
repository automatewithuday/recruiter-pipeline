"""Stage 6: recruiter notes (why this tier, what to ask on a call) for Good/Possible Fit, by Haiku through `claude -p`."""
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from . import criteria, tier

_PROMPT = Path(__file__).parent / "prompts" / "notes.md"
BATCH = 5  # profiles per Haiku call, amortises the fixed `claude -p` overhead


def ask(prompt: str) -> str:
    r = subprocess.run(["claude", "-p", "--model", "haiku", "--output-format", "text"],
                       input=prompt, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"claude -p failed: {r.stderr.strip()[:300]}")
    return r.stdout


def entry(row: dict, profile: dict, scores: dict, spec: dict, today: date) -> dict:
    th = spec["thresholds"]
    dims = [{"dimension": d["name"], "must_have": d["must_have"], "score": round(scores[d["id"]]["score"], 2),
             "gap": scores[d["id"]]["score"] < th["good_must_have_min"] or scores[d["id"]]["confidence"] < th["low_confidence"],
             "strong_looks_like": d["levels"][2]} for d in spec["soft"] if d["id"] in scores]
    return {"tier": row["tier"], "total_years": row["total_years"], "stack_years": row["stack_years"],
            "gate_flags": row["gate_notes"], "dimensions": dims, "profile": tier._state(profile, today)}


def write(entries: dict[str, dict], spec: dict, ask=ask, workers: int = 4) -> dict[str, dict]:
    """entries: url -> entry(). Returns url -> {tier, reasoning, ask_on_call}; a failed batch is simply absent."""
    urls = list(entries)
    batches = [urls[i:i + BATCH] for i in range(0, len(urls), BATCH)]
    head = f"{_PROMPT.read_text()}\n\nROLE: {spec['slug']}\nHARD REQUIREMENTS: {json.dumps(spec['hard'], ensure_ascii=False)}"

    def one(batch: list[str]) -> dict:
        payload = {str(i): entries[u] for i, u in enumerate(batch, 1)}
        try:
            out = criteria._extract_json(ask(f"{head}\n\nCANDIDATES:\n{json.dumps(payload, ensure_ascii=False)}"))
        except Exception:  # bad JSON or CLI failure: rows stay without notes, the next run retries them
            return {}
        got = {}
        for i, u in enumerate(batch, 1):
            o = out.get(str(i))
            if isinstance(o, dict) and o.get("reasoning") and isinstance(o.get("ask_on_call"), list):
                got[u] = {"tier": entries[u]["tier"], "reasoning": str(o["reasoning"]), "ask_on_call": [str(q) for q in o["ask_on_call"]]}
        return got

    notes: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for got in ex.map(one, batches):
            notes.update(got)
    return notes
