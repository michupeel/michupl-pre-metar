"""Local dashboard entrypoint; source collection is never started here."""

import argparse

from premetar.dashboard.app import run

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--port", type=int, default=8765)
args = parser.parse_args()
if not 1024 <= args.port <= 65535:
    parser.error("Port must be1024..65535")
run(args.port)
