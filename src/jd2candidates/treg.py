"""Thin wrapper over the authenticated `treg` CLI. JSON on stdout, charge on stderr."""
import json
import re
import subprocess

_CHARGE = re.compile(r"charged \$([0-9.]+)")


class TregError(RuntimeError):
    pass


def call(tool: str, params: dict[str, str]) -> tuple[dict, float]:
    argv = ["treg", "call", tool]
    for k, v in params.items():
        argv += ["-p", f"{k}={v}"]
    r = subprocess.run(argv, capture_output=True, text=True)
    if r.returncode != 0:
        raise TregError(r.stderr.strip() or r.stdout.strip())
    m = _CHARGE.search(r.stderr)
    data = json.loads(r.stdout)
    if isinstance(data, dict) and data.get("error"):  # provider 4xx arrives with rc 0
        raise TregError(f"{tool}: {data['error']}")
    return data, float(m.group(1)) if m else 0.0
