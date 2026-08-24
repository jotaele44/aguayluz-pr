#!/usr/bin/env python3
"""Run the bounded, artifact-only Laguna Cartagena current-condition probe."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from operators.laguna_cartagena_probe import run_probe  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/laguna_cartagena_live_probe"),
    )
    receipt = run_probe(parser.parse_args().output_dir)
    print(
        json.dumps(
            {
                "outcome": receipt["outcome"],
                "candidate_observation_count": receipt["candidate_observation_count"],
                "eligible_observation_count": receipt["eligible_observation_count"],
                "direct_current_observation_count": receipt[
                    "direct_current_observation_count"
                ],
                "missing_required_metrics": receipt["missing_required_metrics"],
                "replay_failures": receipt["replay_failures"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
