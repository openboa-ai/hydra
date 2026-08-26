#!/usr/bin/env python3
"""Create a detached-trust attestation for a control-plane-collected canary record."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_PATH = ROOT / "scripts/evaluate_outcome_canary.py"


def _load_evaluator():
    spec = importlib.util.spec_from_file_location("evaluate_outcome_canary", EVALUATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load outcome canary evaluator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        evaluator = _load_evaluator()
        key = evaluator.read_bounded_regular_file(
            args.key_file, evaluator.MAX_KEY_BYTES, "attestation key", require_private=True,
        )
        if len(key) < 32:
            raise ValueError("attestation key must contain at least 32 bytes")
        record_bytes = evaluator.read_bounded_regular_file(
            args.record, evaluator.MAX_RECORD_BYTES, "record",
        )
        evaluator.validate_json_structure(record_bytes)
        payload = json.loads(
            record_bytes.decode("utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-standard JSON constant: {value}")
            ),
        )
        if not isinstance(payload, dict):
            raise ValueError("outcome canary record must be a JSON object")
        if "attestation" in payload:
            raise ValueError("input record must not already contain an attestation")
        payload["attestation"] = evaluator.create_attestation(payload, key)
        rendered = (
            json.dumps(
                payload, ensure_ascii=False, allow_nan=False, sort_keys=True,
                separators=(",", ":"),
            ) + "\n"
        ).encode("utf-8")
        if len(rendered) > evaluator.MAX_RECORD_BYTES:
            raise ValueError(
                f"attested record exceeds {evaluator.MAX_RECORD_BYTES} bytes"
            )
        args.output.write_bytes(rendered)
    except (
        OSError, OverflowError, RecursionError, UnicodeDecodeError,
        json.JSONDecodeError, RuntimeError, ValueError,
    ) as exc:
        print(f"cannot attest outcome canary record: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
