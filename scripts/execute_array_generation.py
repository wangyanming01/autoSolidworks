from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from build_array_model import apply_delete_selection, generate_array_plan


def build_execution_payload(config: dict[str, Any], delete_ids: list[str] | None = None) -> dict[str, Any]:
    plan = generate_array_plan(config)
    if delete_ids:
        plan = apply_delete_selection(plan, delete_ids)

    steps: list[dict[str, Any]] = []
    for entry in plan["manifest"]:
        steps.append(
            {
                "logical_id": entry["logical_id"],
                "layer": entry["layer"],
                "sector": entry["sector"],
                "body_type": entry["body_type"],
                "angle_deg": entry["angle_deg"],
                "translation_mm": entry["translation_mm"],
                "action": "generate_body",
            }
        )

    return {
        "config": plan["config"],
        "angle_step_deg": plan["angle_step_deg"],
        "manifest": plan["manifest"],
        "delete_manifest": plan["delete_manifest"],
        "steps": steps,
        "total_entities": plan["total_entities"],
        "delete_count": len(plan["delete_manifest"]),
    }


def write_execution_payload(config: dict[str, Any], output_path: str | Path, delete_ids: list[str] | None = None) -> dict[str, Any]:
    payload = build_execution_payload(config, delete_ids=delete_ids)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute the logical array-generation plan for the layered three-body unit.")
    parser.add_argument("--config", type=Path, default=Path("configs/valve_core_array.example.json"), help="JSON config for the layered base unit")
    parser.add_argument("--output", type=Path, default=Path("outputs/generated/array-execution.json"), help="Where to write the execution payload")
    parser.add_argument("--delete", nargs="*", default=[], help="Logical IDs to delete after generation")
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    payload = write_execution_payload(config, args.output, delete_ids=args.delete)
    print(json.dumps(
        {
            "total_entities": payload["total_entities"],
            "delete_count": payload["delete_count"],
            "first_id": payload["manifest"][0]["logical_id"],
            "last_id": payload["manifest"][-1]["logical_id"],
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
