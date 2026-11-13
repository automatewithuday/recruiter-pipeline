import json
from jd2candidates import notes

SPEC = {"slug": "role-in", "hard": {"min_stack_years": 8}}


def test_write_batches_maps_keys_to_urls_and_survives_a_bad_batch():
    entries = {f"u{i}": {"tier": "Possible Fit"} for i in range(7)}
    calls = []
    def ask(prompt):
        calls.append(prompt)
        if len(calls) == 2:
            return "sorry, no JSON"
        n = len(json.loads(prompt.split("CANDIDATES:\n")[1]))
        return json.dumps({str(i): {"reasoning": f"r{i}", "ask_on_call": ["q"]} for i in range(1, n + 1)})
    out = notes.write(entries, SPEC, ask=ask, workers=1)
    assert len(calls) == 2 and list(out) == [f"u{i}" for i in range(5)]
    assert out["u1"] == {"tier": "Possible Fit", "reasoning": "r2", "ask_on_call": ["q"]}
