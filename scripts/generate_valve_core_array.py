from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import pythoncom
import win32com.client

REPO_ROOT = Path(__file__).resolve().parents[1]
ADAPTER_DIR = REPO_ROOT / "adapters" / "claude"
sys.path.insert(0, str(ADAPTER_DIR))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from execution_client import call_tool, ensure_ready, get_state  # noqa: E402
from apply_valve_core_unit_params import (
    DEFAULT_MODEL_PATH,
    DEFAULT_OUTPUT_DIR,
    apply_params,
    create_model_copy,
    current_doc_title,
    load_params,
    make_output_path,
    open_model,
    part_name_for_doc,
    validate_params,
)


DEFAULT_TOP_CAP_PATH = REPO_ROOT / "base_models" / "顶盖_标准化.SLDPRT"


def get_doc():
    sw = win32com.client.GetActiveObject("SldWorks.Application")
    doc = sw.ActiveDoc
    if doc is None:
        raise RuntimeError("SolidWorks has no active document.")
    return sw, doc


def create_circular_pattern(doc, axis_name: str, sector_count: int) -> str:
    ext = doc.Extension
    callout = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
    bodies = doc.GetBodies2(0, True)
    if not bodies:
        raise RuntimeError("No solid bodies found to circular pattern.")

    doc.ClearSelection2(True)
    if not ext.SelectByID2(axis_name, "AXIS", 0.0, 0.0, 0.0, False, 1, callout, 0):
        raise RuntimeError(f"Failed to select axis '{axis_name}' for circular pattern.")

    for b in bodies:
        if not ext.SelectByID2(b.Name, "SOLIDBODY", 0.0, 0.0, 0.0, True, 256, callout, 0):
            raise RuntimeError(f"Failed to select solid body '{b.Name}' for circular pattern.")

    feat_mgr = doc.FeatureManager
    feat = feat_mgr.FeatureCircularPattern4(sector_count, 2.0 * math.pi, False, "", False, True, False)
    if not feat:
        raise RuntimeError("SolidWorks FeatureCircularPattern4 returned null.")
    return feat.Name


def create_linear_pattern(doc, axis_name: str, layer_count: int, layer_pitch_m: float) -> str:
    if layer_count <= 1:
        return ""
    ext = doc.Extension
    callout = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
    bodies = doc.GetBodies2(0, True)
    if not bodies:
        raise RuntimeError("No solid bodies found to linear pattern.")

    doc.ClearSelection2(True)
    if not ext.SelectByID2(axis_name, "AXIS", 0.0, 0.0, 0.0, False, 1, callout, 0):
        raise RuntimeError(f"Failed to select axis '{axis_name}' for linear pattern.")

    for b in bodies:
        if not ext.SelectByID2(b.Name, "SOLIDBODY", 0.0, 0.0, 0.0, True, 256, callout, 0):
            raise RuntimeError(f"Failed to select solid body '{b.Name}' for linear pattern.")

    feat_mgr = doc.FeatureManager
    # FeatureLinearPattern3(Num1, Spacing1, Num2, Spacing2, FlipDir1, FlipDir2, DName1, DName2, GeometryPattern, VaryInstance)
    feat = feat_mgr.FeatureLinearPattern3(layer_count, layer_pitch_m, 1, 0.01, False, False, "", "", False, False)
    if not feat:
        raise RuntimeError("SolidWorks FeatureLinearPattern3 returned null.")
    return feat.Name


def identify_and_map_bodies(doc, layer_count: int, sector_count: int, layer_pitch_mm: float, base_thickness_mm: float) -> list[dict[str, Any]]:
    bodies = doc.GetBodies2(0, True)
    body_records = []

    for b in bodies:
        box = b.GetBodyBox()
        ymin_mm = box[1] * 1000.0
        ymax_mm = box[4] * 1000.0
        height_mm = ymax_mm - ymin_mm
        cx = (box[0] + box[3]) / 2.0 * 1000.0
        cy = (box[1] + box[4]) / 2.0 * 1000.0
        cz = (box[2] + box[5]) / 2.0 * 1000.0
        r_xz = math.hypot(cx, cz)
        angle_deg = math.degrees(math.atan2(cz, cx))
        if angle_deg < 0:
            angle_deg += 360.0

        # Layer determination from Y coordinate
        layer = int(ymin_mm // layer_pitch_mm) + 1 if layer_pitch_mm > 0 else 1
        layer = max(1, min(layer_count, layer))

        # Body type determination
        if height_mm <= (base_thickness_mm + 1e-2):
            b_type = "base"
        elif r_xz < 18.0:
            b_type = "inner"
        else:
            b_type = "side"

        body_records.append({
            "name": b.Name,
            "body_obj": b,
            "layer": layer,
            "body_type": b_type,
            "cy": cy,
            "cx": cx,
            "cz": cz,
            "r_xz": r_xz,
            "angle_deg": angle_deg,
        })

    # Sort sectors per (layer, body_type) by angular order
    mapped: list[dict[str, Any]] = []
    for l in range(1, layer_count + 1):
        for bt in ["base", "inner", "side"]:
            group = [r for r in body_records if r["layer"] == l and r["body_type"] == bt]
            group.sort(key=lambda r: r["angle_deg"])
            for s_idx, r in enumerate(group, start=1):
                logical_id = f"L{l}_S{s_idx}_{bt}"
                r_copy = dict(r)
                r_copy.pop("body_obj", None)
                r_copy["sector"] = s_idx
                r_copy["logical_id"] = logical_id
                mapped.append(r_copy)

    return mapped


def delete_solid_bodies(doc, body_names_to_delete: list[str]) -> str:
    if not body_names_to_delete:
        return ""
    ext = doc.Extension
    callout = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
    doc.ClearSelection2(True)
    for name in body_names_to_delete:
        ext.SelectByID2(name, "SOLIDBODY", 0.0, 0.0, 0.0, True, 1, callout, 0)

    feat_mgr = doc.FeatureManager
    feat = feat_mgr.InsertDeleteBody2(False)
    if not feat:
        raise RuntimeError("SolidWorks InsertDeleteBody2 failed.")
    return feat.Name


def save_active_doc(doc) -> dict[str, Any]:
    errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    ok = bool(doc.Save3(1, errors, warnings))
    return {"save3": ok, "errors": errors.value, "warnings": warnings.value}


def prepare_top_cap_model(template_cap_path: Path, output_cap_path: Path, outer_radius_m: float, inner_radius_m: float, thickness_m: float, overwrite: bool = True) -> Path:
    """Create a customized top cap model copy and apply parameters from JSON:

    - Outer Radius: outer_diameter_mm / 2
    - Inner Radius: inner_radius_mm
    - Thickness: base_thickness_mm
    """
    output_cap_path = create_model_copy(template_cap_path, output_cap_path, overwrite=overwrite)

    open_model(output_cap_path)
    sw, doc = get_doc()
    title = current_doc_title(doc)
    part_name = part_name_for_doc(doc)

    ext = doc.Extension
    callout = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)

    # Edit sketch1 to adjust inner and outer circle radii
    ext.SelectByID2("草图1", "SKETCH", 0, 0, 0, False, 0, callout, 0)
    doc.EditSketch()
    sketch = doc.SketchManager.ActiveSketch
    segs = sketch.GetSketchSegments
    if len(segs) >= 2:
        # Seg 0 is inner circle (R2), Seg 1 is outer circle (R0)
        # Ensure correct mapping based on existing radii
        r0 = segs[0].GetRadius
        r1 = segs[1].GetRadius
        if r0 < r1:
            segs[0].SetRadius(float(inner_radius_m))
            segs[1].SetRadius(float(outer_radius_m))
        else:
            segs[0].SetRadius(float(outer_radius_m))
            segs[1].SetRadius(float(inner_radius_m))
    doc.SketchManager.InsertSketch(True)

    # Update thickness dimension: D1@顶盖@<PartName>
    p_thick = doc.Parameter(f"D1@顶盖@{part_name}")
    if p_thick:
        p_thick.SystemValue = float(thickness_m)

    doc.ForceRebuild3(False)

    # Save and close
    save_res = save_active_doc(doc)
    if not save_res["save3"] or save_res["errors"] != 0:
        raise RuntimeError(f"Failed to save customized top cap: {save_res}")

    close_doc(sw, doc)
    return output_cap_path


def insert_and_position_top_cap(doc, cap_model_path: Path, z_top_m: float) -> str:
    """Insert top cap solid body into the valve core part and move it onto the top face.

    Aligns alpha0 with the top face of the layered array (Y = z_top_m)
    and axis with the center rotation axis (axis0/axis1).
    """
    part = doc
    # Insert part body (swInsertPartOptions_SolidBodies = 1)
    feat = part.InsertPart3(str(cap_model_path), 1, "")
    if not feat:
        raise RuntimeError(f"Failed to insert top cap part: {cap_model_path}")

    ext = doc.Extension
    callout = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)

    # Locate the inserted cap body
    bodies = doc.GetBodies2(0, True)
    cap_body_name = None
    for b in bodies:
        if "顶盖" in b.Name or feat.Name in b.Name:
            cap_body_name = b.Name
            break

    if not cap_body_name:
        raise RuntimeError("Could not find inserted top cap solid body in model.")

    # Move body in Y direction by z_top_m
    doc.ClearSelection2(True)
    if not ext.SelectByID2(cap_body_name, "SOLIDBODY", 0.0, 0.0, 0.0, False, 1, callout, 0):
        raise RuntimeError(f"Failed to select top cap body '{cap_body_name}' for positioning.")

    feat_mgr = doc.FeatureManager
    # InsertMoveCopyBody2: 12 args (transX, transY, transZ, copy, rotX, rotY, rotZ, angle, origX, origY, origZ, invertDir)
    move_feat = feat_mgr.InsertMoveCopyBody2(0.0, float(z_top_m), 0.0, False, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, False)
    if not move_feat:
        raise RuntimeError("SolidWorks InsertMoveCopyBody2 failed for top cap.")

    return move_feat.Name


def execute_full_array_generation(
    config_path: Path,
    output_path: Path | None = None,
    overwrite: bool = True,
    include_top_cap: bool = True,
    keep_open: bool = False,
    base_model_path: Path = DEFAULT_MODEL_PATH,
    top_cap_model_path: Path = DEFAULT_TOP_CAP_PATH,
) -> dict[str, Any]:
    with config_path.open("r", encoding="utf-8") as f:
        config = json.load(f)

    unit_p = config.get("unit_params", {}) or {}
    array_p = config.get("array_params", {}) or {}
    custom_c = config.get("custom_clearance", {}) or {}

    merged_unit_params = dict(unit_p)
    merged_unit_params.update(array_p)
    validated_unit_params = validate_params(load_params(config_path))

    layer_count = int(array_p.get("layer_count", 1))
    sector_count = int(array_p.get("sector_count", 8))
    base_thickness_mm = float(unit_p.get("base_thickness_mm", 10.0))
    wall_height_mm = float(unit_p.get("wall_height_mm", 40.0))
    layer_pitch_mm = base_thickness_mm + wall_height_mm
    layer_pitch_m = layer_pitch_mm / 1000.0
    total_height_m = (layer_count * layer_pitch_mm) / 1000.0

    delete_requested = list(custom_c.get("delete_bodies", []))

    # Step 1: Copy base template
    if output_path is None:
        output_path = DEFAULT_OUTPUT_DIR / f"{config_path.stem}.SLDPRT"
    target_model = create_model_copy(base_model_path, output_path, overwrite=overwrite)

    # Step 2: Open and apply base unit parameters
    unit_result = apply_params(validated_unit_params, target_model, save=False)
    sw, doc = get_doc()

    # Step 3: Circular pattern
    cir_feat = create_circular_pattern(doc, "axis0", sector_count)

    # Step 4: Linear pattern (if layer_count > 1)
    lin_feat = create_linear_pattern(doc, "axis0", layer_count, layer_pitch_m) if layer_count > 1 else ""

    # Rebuild
    doc.ForceRebuild3(False)

    # Step 5: Identify and map all solid bodies to Logical IDs
    mapped_bodies = identify_and_map_bodies(doc, layer_count, sector_count, layer_pitch_mm, base_thickness_mm)

    # Step 6: Map requested delete IDs to actual SolidWorks body names
    id_to_body_name = {b["logical_id"]: b["name"] for b in mapped_bodies}
    bodies_to_delete = [id_to_body_name[lid] for lid in delete_requested if lid in id_to_body_name]

    # Step 7: Delete bodies
    del_feat = delete_solid_bodies(doc, bodies_to_delete) if bodies_to_delete else ""
    doc.ForceRebuild3(False)

    # Step 8: Prepare customized top cap as a disposable build artifact.
    top_cap_feat = ""
    top_cap_temp_dir = None
    try:
        if include_top_cap:
            if not top_cap_model_path.is_file():
                raise FileNotFoundError(f"Top cap template not found: {top_cap_model_path}")
            top_cap_temp_dir = tempfile.TemporaryDirectory(prefix="solidpilot-top-cap-")
            customized_cap_path = Path(top_cap_temp_dir.name) / "top_cap.SLDPRT"
            prepared_cap_path = prepare_top_cap_model(
                template_cap_path=top_cap_model_path,
                output_cap_path=customized_cap_path,
                outer_radius_m=validated_unit_params["outer_radius_mm"] / 1000.0,
                inner_radius_m=validated_unit_params["inner_radius_mm"] / 1000.0,
                thickness_m=validated_unit_params["base_thickness_mm"] / 1000.0,
                overwrite=True,
            )
            top_cap_feat = insert_and_position_top_cap(doc, prepared_cap_path, total_height_m)
            doc.ForceRebuild3(False)

        # Final bodies count
        final_bodies = doc.GetBodies2(0, True)
        final_count = len(final_bodies) if final_bodies else 0

        # Save the self-contained result before removing temporary source geometry.
        save_res = save_active_doc(doc)
    finally:
        if top_cap_temp_dir is not None:
            close_doc(sw, doc)
            doc = None
            pythoncom.CoFreeUnusedLibraries()
            top_cap_temp_dir.cleanup()
            if keep_open:
                open_model(target_model)

    return {
        "status": "COMPLETED",
        "output_model": str(target_model),
        "total_generated_entities": len(mapped_bodies),
        "circular_pattern_feature": cir_feat,
        "linear_pattern_feature": lin_feat,
        "deleted_features": del_feat,
        "top_cap_feature": top_cap_feat,
        "deleted_logical_ids": delete_requested,
        "deleted_body_names": bodies_to_delete,
        "final_body_count": final_count,
        "mapped_manifest": mapped_bodies,
        "save": save_res,
    }


def close_doc(sw, doc) -> None:
    value = doc.GetTitle
    title = value() if callable(value) else value
    sw.CloseDoc(title)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate full multi-layer, multi-sector SolidWorks valve core array model with custom clearance and top cap.")
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "configs" / "valve_core_array.example.json")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "outputs" / "generated" / "valve_core_array_final.SLDPRT")
    parser.add_argument("--base-model", type=Path, default=DEFAULT_MODEL_PATH, help="Base unit template model path.")
    parser.add_argument("--top-cap-model", type=Path, default=DEFAULT_TOP_CAP_PATH, help="Top cap template model path.")
    parser.add_argument("--overwrite", action="store_true", default=True)
    parser.add_argument("--no-top-cap", action="store_true", help="Do not insert top cap into final model.")
    parser.add_argument("--keep-open", action="store_true", help="Keep the document open in SolidWorks GUI after generation.")
    args = parser.parse_args()

    result = execute_full_array_generation(
        args.config,
        args.output,
        overwrite=args.overwrite,
        include_top_cap=not args.no_top_cap,
        keep_open=args.keep_open,
        base_model_path=args.base_model,
        top_cap_model_path=args.top_cap_model,
    )

    if not args.keep_open:
        try:
            sw, doc = get_doc()
            close_doc(sw, doc)
        except Exception:
            pass

    print(json.dumps({
        "status": result["status"],
        "output_model": result["output_model"],
        "total_generated_entities": result["total_generated_entities"],
        "circular_pattern_feature": result["circular_pattern_feature"],
        "linear_pattern_feature": result["linear_pattern_feature"],
        "deleted_features": result["deleted_features"],
        "top_cap_feature": result["top_cap_feature"],
        "deleted_logical_ids": result["deleted_logical_ids"],
        "final_body_count": result["final_body_count"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
