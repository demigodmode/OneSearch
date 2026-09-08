"""Sign SHA256SUMS with the raw Ed25519 release key."""

from __future__ import annotations

import argparse
from pathlib import Path

from onesearch_agent.packaging import sign_bytes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--private-key", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_bytes(sign_bytes(args.input.read_bytes(), args.private_key))


if __name__ == "__main__":
    main()
