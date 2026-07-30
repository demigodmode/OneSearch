"""Create the canonical signed release manifest consumed by the native updater."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from onesearch_agent.packaging import sign_manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--private-key", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    envelope = sign_manifest(
        artifact=args.artifact,
        platform=args.platform,
        version=args.version,
        url=args.url,
        private_key=args.private_key,
    )
    args.output.write_text(json.dumps(envelope, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
