from __future__ import annotations

import argparse
import json
from pathlib import Path

from .certify_usdm import certify
from .manifest import verify_manifest_file


def replay(manifest_path: Path, manifest_sha256: str) -> dict[str, object]:
    verify_manifest_file(manifest_path, manifest_sha256)
    result = certify(manifest_path)
    return {
        "manifest_sha256": manifest_sha256,
        "certification": result,
        "network_required": False,
        "status": "replay_pass",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(replay(args.manifest, args.manifest_sha256), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
