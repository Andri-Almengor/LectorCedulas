"""QA16: CLI local de preparación, sin solicitar datos personales ni usar BLE."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .profile_readiness import MAX_CERT, MAX_PROFILE, inspect_profile_readiness


def _read_bounded(path: Path | None, limit: int) -> bytes | None:
    if path is None:
        return None
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("material_too_large")
    return raw


def run(argv=None):
    parser = argparse.ArgumentParser(description="IDC: preparación local del perfil (no verifica identidad)")
    parser.add_argument("--profile", type=Path, help="Perfil JSON recibido de una fuente técnica confiable")
    parser.add_argument("--anchor-der", type=Path, help="Certificado candidato IACA DER")
    parser.add_argument("--anchor-pin-file", type=Path, help="Huella SHA-256 DER de fuente independiente")
    args = parser.parse_args(argv)
    try:
        profile = _read_bounded(args.profile, MAX_PROFILE)
        anchor = _read_bounded(args.anchor_der, MAX_CERT)
        pin_raw = _read_bounded(args.anchor_pin_file, 128)
        pin = pin_raw.decode("ascii").strip().lower() if pin_raw is not None else None
        report = inspect_profile_readiness(
            profile, candidate_iaca_der=anchor, independently_pinned_sha256=pin
        )
    except (OSError, ValueError):
        report = inspect_profile_readiness(None)
        report["status"] = "local_material_unreadable_or_invalid"
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "candidate_profile_structurally_ready_not_verified" else 2


if __name__ == "__main__":
    raise SystemExit(run())
