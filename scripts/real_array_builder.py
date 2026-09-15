from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from build_array_model import apply_delete_selection, generate_array_plan


def build_execution_plan(config: dict[str, Any], delete_ids: list[str] | None = None) -> dict[str, Any]:
    """Build the executable array recipe for a real part-generation workflow.

    This stage does not directly touch SolidWorks; it turns the business-level
    configuration into a deterministic execution plan that can later be fed to
    the SolidWorks adapter or to a direct COM script.
    """
    plan = generate_array_plan(config)
    if delete_ids:
        plan = apply_delete_selection(plan, delete_ids)

    steps: list[dict[str, Any]] = []
    for item in plan["manifest"]:
        steps.append(
            {
                "logical_id": item["logical_id"],
                "layer": item["layer"],
                "sector": item["sector"],
                "body_type": item["body_type"],
                "angle_deg": item["angle_deg"],
                "translation_mm": item["translation_mm"],
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
    }


def write_execution_plan_json(config: dict[str, Any], output_path: str | Path, delete_ids: list[str] | None = None) -> dict[str, Any]:
    plan = build_execution_plan(config, delete_ids=delete_ids)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an executable array recipe for the layered three-body unit.")
    parser.add_argument("--config", type=Path, help="JSON config file for the array generation")
    parser.add_argument("--output", type=Path, default=Path("outputs/generated/real-array-plan.json"))
    parser.add_argument("--delete", nargs="*", default=[], help="Logical IDs to delete after generation")
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8")) if args.config else {
        "layer_count": 2,
        "sector_count": 8,
        "layer_pitch_mm": 25.0,
        "body_types": ["base", "inner", "side"],
    }

    result = write_execution_plan_json(config, args.output, delete_ids=args.delete)
    print(json.dumps({
        "total_entities": result["total_entities"],
        "delete_count": len(result["delete_manifest"]),
        "steps": len(result["steps"]),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
