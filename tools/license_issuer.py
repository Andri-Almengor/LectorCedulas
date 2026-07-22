from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from template.assets.runtime.hardened.atomic_io import write_json_atomic
from template.assets.runtime.hardened.license_service import generate_keypair, issue_license


def default_secret_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "DMS" / "LectorCedulasDashboard" / "secrets"


def main() -> int:
    parser = argparse.ArgumentParser(description="Emite licencias Ed25519 para Lector Cédulas DMS")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--days", type=int, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--installation-id")
    parser.add_argument("--secret-dir", default=str(default_secret_dir()))
    parser.add_argument("--public-output", default="template/assets/license_public_key.pem")
    args = parser.parse_args()
    if args.days <= 0 or args.days > 3650:
        parser.error("--days debe estar entre 1 y 3650")
    secret_dir = Path(args.secret_dir)
    private_path = secret_dir / "license_ed25519_private.pem"
    public_secret_path = secret_dir / "license_ed25519_public.pem"
    if not private_path.exists():
        generate_keypair(private_path, public_secret_path)
    public_output = Path(args.public_output)
    public_output.parent.mkdir(parents=True, exist_ok=True)
    public_output.write_bytes(public_secret_path.read_bytes())
    issued = datetime.now(timezone.utc)
    envelope = issue_license(
        private_key_path=private_path,
        client_id=args.client_id,
        license_id=f"LIC-{uuid.uuid4().hex.upper()}",
        issued_at_utc=issued,
        expires_at_utc=issued + timedelta(days=args.days),
        installation_id=args.installation_id,
    )
    write_json_atomic(args.output, envelope, backup=False)
    print(json.dumps({"output": args.output, "public_key": str(public_output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
