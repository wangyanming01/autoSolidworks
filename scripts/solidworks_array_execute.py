from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from build_array_manifest import build_delete_manifest


def load_execution_payload(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if "manifest" not in payload:
        raise ValueError(f"Execution payload is missing manifest: {path}")
    if "steps" not in payload and "delete_manifest" in payload:
        payload["steps"] = [
            {"logical_id": item["logical_id"], "status": "pending"}
            for item in payload["manifest"]
        ]
    if "steps" not in payload:
        raise ValueError(f"Execution payload is missing steps: {path}")
    return payload


def build_tasks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for entry in payload["manifest"]:
        tasks.append(
            {
                "logical_id": entry["logical_id"],
                "layer": entry["layer"],
                "sector": entry["sector"],
                "body_type": entry["body_type"],
                "angle_deg": entry["angle_deg"],
                "translation_mm": entry["translation_mm"],
                "status": "pending",
            }
        )
    return tasks


def assign_real_bodies_to_manifest(body_list: list[dict[str, Any]], manifest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(body_list) != len(manifest):
        raise ValueError(f"Body count mismatch: expected {len(manifest)} real bodies, got {len(body_list)}")

    assigned: list[dict[str, Any]] = []
    for body, entry in zip(body_list, manifest):
        item = dict(body)
        item["logical_id"] = entry["logical_id"]
        item["layer"] = entry["layer"]
        item["sector"] = entry["sector"]
        item["body_type"] = entry["body_type"]
        assigned.append(item)
    return assigned


def map_delete_targets(real_bodies: list[dict[str, Any]], delete_manifest: list[dict[str, Any]]) -> list[str]:
    targets = build_delete_manifest(real_bodies, [item["logical_id"] for item in delete_manifest])
    return [item["name"] for item in targets]


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run the SolidWorks array-generation workflow from an execution payload.")
    parser.add_argument("--payload", type=Path, default=Path("outputs/generated/array-execution.json"), help="Execution payload JSON produced by the array generator")
    parser.add_argument("--output", type=Path, default=Path("outputs/generated/solidworks-array-run.json"), help="Write the generated execution report")
    parser.add_argument("--execute", action="store_true", help="Attempt to execute the real SolidWorks workflow; default is dry-run only.")
    args = parser.parse_args()

    payload = load_execution_payload(args.payload)
    tasks = build_tasks(payload)
    report = {
        "mode": "execute" if args.execute else "dry-run",
        "total_entities": len(tasks),
        "delete_count": len(payload.get("delete_manifest", [])),
        "tasks": tasks,
        "delete_manifest": payload.get("delete_manifest", []),
    }

    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "mode": report["mode"],
        "total_entities": report["total_entities"],
        "delete_count": report["delete_count"],
        "output": str(path),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
