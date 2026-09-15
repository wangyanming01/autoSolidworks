from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    # 如果已经是经过 validate_config 处理后的字典，直接返回
    if "_validated" in config:
        return config

    # 兼容嵌套结构 (unit_params + array_params) 与扁平结构
    unit_params = config.get("unit_params", {}) or {}
    array_params = config.get("array_params", {}) or {}

    layer_count = int(array_params.get("layer_count", config.get("layer_count", 1)))
    sector_count = int(array_params.get("sector_count", config.get("sector_count", 1)))

    base_thickness = float(unit_params.get("base_thickness_mm", config.get("base_thickness_mm", 0.0)))
    wall_height = float(unit_params.get("wall_height_mm", config.get("wall_height_mm", 0.0)))

    # 自动计算层高：当有底板厚度与壁高时，层间距自动堆叠
    auto_pitch = base_thickness + wall_height
    if auto_pitch > 0:
        layer_pitch_mm = auto_pitch
    else:
        layer_pitch_mm = float(array_params.get("layer_pitch_mm", config.get("layer_pitch_mm", 0.0)))

    body_types = config.get("body_types", ["base", "inner", "side"])

    if layer_count < 1:
        raise ValueError("layer_count must be >= 1")
    if sector_count < 3:
        raise ValueError("sector_count must be >= 3")
    if layer_pitch_mm < 0:
        raise ValueError("layer_pitch_mm must be >= 0")
    if not body_types:
        raise ValueError("body_types must not be empty")

    custom_clearance = config.get("custom_clearance", {}) or {}
    delete_bodies = custom_clearance.get("delete_bodies", config.get("delete_bodies", []))

    return {
        "_validated": True,
        "layer_count": layer_count,
        "sector_count": sector_count,
        "layer_pitch_mm": layer_pitch_mm,
        "body_types": list(body_types),
        "unit_params": unit_params if unit_params else None,
        "delete_bodies": list(delete_bodies),
    }


def build_manifest(config: dict[str, Any]) -> list[dict[str, Any]]:
    cfg = validate_config(config)
    manifest: list[dict[str, Any]] = []

    for layer in range(1, cfg["layer_count"] + 1):
        z_offset_mm = (layer - 1) * cfg["layer_pitch_mm"]
        for sector in range(1, cfg["sector_count"] + 1):
            angle_deg = 360.0 / cfg["sector_count"] * (sector - 1)
            for body_type in cfg["body_types"]:
                manifest.append(
                    {
                        "logical_id": f"L{layer}_S{sector}_{body_type}",
                        "layer": layer,
                        "sector": sector,
                        "body_type": body_type,
                        "angle_deg": angle_deg,
                        "translation_mm": [0.0, 0.0, float(z_offset_mm)],
                        "rotation_axis": "z",
                    }
                )

    return manifest


def build_delete_manifest(manifest: list[dict[str, Any]], logical_ids: list[str]) -> list[dict[str, Any]]:
    delete_set = set(logical_ids)
    return [item for item in manifest if item.get("logical_id") in delete_set]


def write_manifest_json(config: dict[str, Any], output_path: str | Path) -> dict[str, Any]:
    cfg = validate_config(config)
    manifest = build_manifest(cfg)
    payload = {
        "config": cfg,
        "manifest": manifest,
        "delete_manifest": [],
    }
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    example = {
        "layer_count": 2,
        "sector_count": 8,
        "layer_pitch_mm": 25.0,
        "body_types": ["base", "inner", "side"],
    }
    print(json.dumps(build_manifest(example), ensure_ascii=False, indent=2)[:400])
