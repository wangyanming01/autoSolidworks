from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from build_array_manifest import build_delete_manifest, build_manifest, validate_config


def _sector_rotation_deg(sector_count: int, sector_index: int) -> float:
    return 360.0 / sector_count * (sector_index - 1)


def assign_logical_ids_to_bodies(bodies: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    cfg = validate_config(config)
    body_types = cfg["body_types"]
    layer_count = cfg["layer_count"]
    sector_count = cfg["sector_count"]
    expected = len(bodies)
    if expected == 0:
        return []

    body_index = 0
    result: list[dict[str, Any]] = []
    for layer in range(1, layer_count + 1):
        for sector in range(1, sector_count + 1):
            for body_type in body_types:
                if body_index >= expected:
                    break
                body = dict(bodies[body_index])
                body["logical_id"] = f"L{layer}_S{sector}_{body_type}"
                body["layer"] = layer
                body["sector"] = sector
                body["body_type"] = body_type
                body["angle_deg"] = _sector_rotation_deg(sector_count, sector)
                if "center" in body:
                    body["center"] = list(body["center"])
                result.append(body)
                body_index += 1
            if body_index >= expected:
                break
        if body_index >= expected:
            break

    if len(result) != expected:
        raise ValueError(f"Expected {expected} bodies to map, got {len(result)}")
    return result


def build_delete_targets(bodies: list[dict[str, Any]], logical_ids: list[str]) -> list[str]:
    ids = set(logical_ids)
    return [body["name"] for body in bodies if body.get("logical_id") in ids]


def generate_array_plan(config: dict[str, Any]) -> dict[str, Any]:
    cfg = validate_config(config)
    manifest = build_manifest(cfg)
    angle_step_deg = 360.0 / cfg["sector_count"]

    delete_manifest = []
    if cfg.get("delete_bodies"):
        delete_manifest = build_delete_manifest(manifest, cfg["delete_bodies"])

    return {
        "config": cfg,
        "angle_step_deg": angle_step_deg,
        "manifest": manifest,
        "delete_manifest": delete_manifest,
        "total_entities": len(manifest),
    }


def apply_delete_selection(plan: dict[str, Any], logical_ids: list[str]) -> dict[str, Any]:
    delete_manifest = build_delete_manifest(plan["manifest"], logical_ids)
    plan = dict(plan)
    plan["delete_manifest"] = delete_manifest
    plan["delete_count"] = len(delete_manifest)
    return plan


def write_plan_json(plan: dict[str, Any], output_path: str | Path) -> dict[str, Any]:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "config": plan["config"],
        "angle_step_deg": plan["angle_step_deg"],
        "manifest": plan["manifest"],
        "delete_manifest": plan["delete_manifest"],
        "total_entities": plan["total_entities"],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a logical array plan for a layered three-body valve unit.")
    parser.add_argument("--config", type=Path, help="JSON config with layer_count, sector_count, layer_pitch_mm, and optional body_types")
    parser.add_argument("--output", type=Path, default=Path("outputs/generated/array-plan.json"), help="Output manifest JSON path")
    parser.add_argument("--delete", nargs="*", default=[], help="Logical IDs to delete, e.g. L1_S1_inner L2_S3_side")
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8")) if args.config else {
        "layer_count": 2,
        "sector_count": 8,
        "layer_pitch_mm": 25.0,
        "body_types": ["base", "inner", "side"],
    }

    plan = generate_array_plan(config)
    if args.delete:
        plan = apply_delete_selection(plan, args.delete)

    result = write_plan_json(plan, args.output)
    print(json.dumps({
        "total_entities": result["total_entities"],
        "angle_step_deg": result["angle_step_deg"],
        "delete_count": len(result["delete_manifest"]),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
