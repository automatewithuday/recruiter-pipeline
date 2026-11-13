import argparse
from pathlib import Path

from . import pipeline


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="jd2candidates", description="JD in, tiered LinkedIn candidate CSV out")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the pipeline on a JD file")
    r.add_argument("jd", type=Path)
    r.add_argument("--budget", type=float, default=10.0, help="USD cap for paid calls this run")
    r.add_argument("--from-stage", type=int, default=0, help="recompute from this stage (1 spec, 2 discover, 3 profiles, 5 scores, 6 notes)")
    r.add_argument("--source", choices=["harvest", "getleads"], default="harvest")
    r.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    a = ap.parse_args(argv)
    pipeline.run(a.jd, budget_usd=a.budget, from_stage=a.from_stage, source=a.source, yes=a.yes)
