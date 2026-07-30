"""Create the canonical signed release manifest consumed by the native updater."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from onesearch_shared import MINIMUM_SUPPORTED_PROTOCOL_VERSION, PROTOCOL_VERSION


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--private-key", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    artifact = args.artifact.read_bytes()
    manifest = {
        "version": args.version,
        "protocol_min": MINIMUM_SUPPORTED_PROTOCOL_VERSION,
        "protocol_max": PROTOCOL_VERSION,
        "platform": args.platform,
        "url": args.url,
        "size": len(artifact),
        "sha256": hashlib.sha256(artifact).hexdigest(),
    }
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(args.private_key, validate=True))
    envelope = {"manifest": manifest, "signature": base64.b64encode(key.sign(payload)).decode()}
    args.output.write_text(json.dumps(envelope, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
