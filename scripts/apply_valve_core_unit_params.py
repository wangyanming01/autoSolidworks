from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import pythoncom
import win32com.client


REPO_ROOT = Path(__file__).resolve().parents[1]
ADAPTER_DIR = REPO_ROOT / "adapters" / "claude"
sys.path.insert(0, str(ADAPTER_DIR))

from execution_client import call_tool, ensure_ready, get_state  # noqa: E402


DEFAULT_MODEL_PATH = REPO_ROOT / "base_models" / "基础模型v2.SLDPRT"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "outputs" / "generated"

SKETCH_BASE = "草图1"
SKETCH_INNER = "草图2"
SKETCH_SIDE = "草图5"


def dimensions_for(part_name: str) -> dict[str, str]:
    return {
        "outer_radius": f"R0@{SKETCH_BASE}@{part_name}",
        "middle_radius": f"R1@{SKETCH_BASE}@{part_name}",
        "inner_radius": f"R2@{SKETCH_INNER}@{part_name}",
        "base_thickness": f"D1@alpha2@{part_name}",
        "wall_height": f"D1@alpha3@{part_name}",
        "side_thickness": f"side_thickness@{SKETCH_SIDE}@{part_name}",
        "theta": f"theta@{SKETCH_BASE}@{part_name}",
        "theta_inner": f"theta_inner@{SKETCH_INNER}@{part_name}",
        "inner_outer_radius": f"D1@{SKETCH_INNER}@{part_name}",
        "side_inner_radius": f"R1_side@{SKETCH_SIDE}@{part_name}",
        "side_outer_radius": f"R0_side@{SKETCH_SIDE}@{part_name}",
    }


def load_params(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        raw = json.load(file)

    if "unit_params" in raw:
        params = dict(raw["unit_params"])
        if "array_params" in raw:
            params.update(raw["array_params"])
    else:
        params = raw

    required = {
        "outer_diameter_mm",
        "middle_radius_mm",
        "inner_radius_mm",
        "sector_count",
        "base_thickness_mm",
        "wall_height_mm",
        "side_thickness_mm",
    }
    missing = sorted(required - params.keys())
    if missing:
        raise ValueError(f"Missing required parameter(s): {', '.join(missing)}")
    return params


def validate_params(params: dict[str, Any]) -> dict[str, float | int]:
    outer_radius = float(params["outer_diameter_mm"]) / 2.0
    middle_radius = float(params["middle_radius_mm"])
    inner_radius = float(params["inner_radius_mm"])
    sector_count = int(params["sector_count"])
    base_thickness = float(params["base_thickness_mm"])
    wall_height = float(params["wall_height_mm"])
    side_thickness = float(params["side_thickness_mm"])

    if sector_count != float(params["sector_count"]):
        raise ValueError("sector_count must be an integer.")
    if sector_count < 3:
        raise ValueError("sector_count must be >= 3.")
    if not (outer_radius > middle_radius > inner_radius > 0):
        raise ValueError("Require outer_diameter_mm / 2 > middle_radius_mm > inner_radius_mm > 0.")
    if base_thickness <= 0 or wall_height <= 0:
        raise ValueError("base_thickness_mm and wall_height_mm must be > 0.")
    if side_thickness <= 0:
        raise ValueError("side_thickness_mm must be > 0.")

    theta = 2.0 * math.pi / sector_count
    middle_chord = 2.0 * middle_radius * math.sin(theta / 2.0)
    outer_chord = 2.0 * outer_radius * math.sin(theta / 2.0)
    if side_thickness >= min(middle_chord, outer_chord):
        raise ValueError(
            "side_thickness_mm is too large for the sector: it must be smaller than "
            f"the available chord ({min(middle_chord, outer_chord):.6g} mm)."
        )

    return {
        "outer_radius_mm": outer_radius,
        "middle_radius_mm": middle_radius,
        "inner_radius_mm": inner_radius,
        "sector_count": sector_count,
        "base_thickness_mm": base_thickness,
        "wall_height_mm": wall_height,
        "side_thickness_mm": side_thickness,
        "theta_rad": theta,
    }


def get_doc():
    sw = win32com.client.GetActiveObject("SldWorks.Application")
    doc = sw.ActiveDoc
    if doc is None:
        raise RuntimeError("SolidWorks has no active document.")
    return sw, doc


def current_doc_path(doc) -> str:
    value = doc.GetPathName
    return value() if callable(value) else value


def current_doc_title(doc) -> str:
    value = doc.GetTitle
    return value() if callable(value) else value


def part_name_for_doc(doc) -> str:
    return f"{Path(current_doc_title(doc)).stem}.Part"


def make_output_path(template_path: Path, config_path: Path, output: Path | None, output_dir: Path) -> Path:
    if output is not None:
        return output
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return output_dir / f"{config_path.stem}-{timestamp}{template_path.suffix}"


def close_if_open(target_path: Path) -> None:
    try:
        sw, doc = get_doc()
        while doc:
            doc_path = current_doc_path(doc)
            if doc_path and Path(doc_path).resolve() == target_path.resolve():
                sw.CloseDoc(current_doc_title(doc))
                break
            break
    except Exception:
        pass


def create_model_copy(template_path: Path, target_path: Path, overwrite: bool) -> Path:
    template_path = template_path.resolve()
    target_path = target_path.resolve()
    if not template_path.is_file():
        raise FileNotFoundError(f"Template model not found: {template_path}")
    if template_path == target_path:
        raise ValueError("Output model path must be different from the template path.")

    # 如果目标文件已经在 SolidWorks 中打开，先将其关闭释放文件占用
    close_if_open(target_path)

    if target_path.exists() and not overwrite:
        raise FileExistsError(f"Output model already exists: {target_path}. Use --overwrite to replace it.")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template_path, target_path)
    return target_path


def open_model(model_path: Path) -> None:
    ready = ensure_ready()
    if not ready.get("comAttached"):
        raise RuntimeError(f"SolidWorks is not ready: {ready}")
    try:
        _, doc = get_doc()
    except RuntimeError:
        doc = None
    if doc is not None and Path(current_doc_path(doc)).resolve() == model_path.resolve():
        return
    state_version = get_state()
    response = call_tool("open_document", str(uuid.uuid4()), state_version, {"file_path": str(model_path)})
    if response.get("status") != "COMPLETED":
        raise RuntimeError(f"open_document failed: {response}")


def equations(equation_mgr) -> list[str]:
    result: list[str] = []
    for index in range(equation_mgr.GetCount):
        result.append(equation_mgr.Equation(index))
    return result


def set_equation_by_lhs(equation_mgr, lhs: str, expression: str) -> dict[str, Any]:
    prefix = f'"{lhs}"'
    for index, equation in enumerate(equations(equation_mgr)):
        if equation.strip().startswith(prefix):
            if equation != expression:
                equation_mgr.Equation(index, expression)
                return {"lhs": lhs, "status": "updated", "index": index, "expression": expression}
            return {"lhs": lhs, "status": "exists", "index": index, "expression": expression}
    added_index = equation_mgr.Add2(-1, expression, True)
    if added_index < 0:
        return {"lhs": lhs, "status": "failed", "index": added_index, "expression": expression}
    return {"lhs": lhs, "status": "added", "index": added_index, "expression": expression}


def force_rebuild(doc) -> None:
    equation_mgr = doc.GetEquationMgr
    try:
        _ = equation_mgr.EvaluateAll
    except Exception:
        pass
    if not doc.ForceRebuild3(False):
        raise RuntimeError("SolidWorks ForceRebuild3(False) failed.")


def clear_equations(equation_mgr) -> None:
    for index in range(equation_mgr.GetCount - 1, -1, -1):
        equation_mgr.Delete(index)


def ensure_standard_equations(equation_mgr, sector_count: int) -> list[dict[str, Any]]:
    return [
        set_equation_by_lhs(equation_mgr, f"D1@{SKETCH_INNER}", f'"D1@{SKETCH_INNER}" = "R1@{SKETCH_BASE}"'),
        set_equation_by_lhs(equation_mgr, f"theta_inner@{SKETCH_INNER}", f'"theta_inner@{SKETCH_INNER}" = "theta@{SKETCH_BASE}"'),
        set_equation_by_lhs(equation_mgr, f"R1_side@{SKETCH_SIDE}", f'"R1_side@{SKETCH_SIDE}" = "R1@{SKETCH_BASE}"'),
        set_equation_by_lhs(equation_mgr, f"R0_side@{SKETCH_SIDE}", f'"R0_side@{SKETCH_SIDE}" = "R0@{SKETCH_BASE}"'),
        set_equation_by_lhs(equation_mgr, "N", f'"N" = {sector_count}'),
        set_equation_by_lhs(equation_mgr, f"theta@{SKETCH_BASE}", f'"theta@{SKETCH_BASE}" = 360 / "N"'),
    ]


def modify_dimension(name: str, value_m: float) -> dict[str, Any]:
    state_version = get_state()
    response = call_tool("modify_dimension", str(uuid.uuid4()), state_version, {"name": name, "value": value_m})
    if response.get("status") != "COMPLETED":
        raise RuntimeError(f"modify_dimension failed for {name}: {response}")
    return response


def set_dimension_direct(doc, name: str, value_m: float) -> None:
    dimension = doc.Parameter(name)
    if dimension is None:
        raise RuntimeError(f"Missing SolidWorks dimension: {name}")
    dimension.SystemValue = value_m


def dimension_value(doc, name: str) -> float:
    dimension = doc.Parameter(name)
    if dimension is None:
        raise RuntimeError(f"Missing SolidWorks dimension: {name}")
    return float(dimension.SystemValue)


def has_named_sketch_dimensions(doc, dimensions: dict[str, str]) -> bool:
    return all(doc.Parameter(dimensions[key]) is not None for key in (
        "outer_radius",
        "middle_radius",
        "inner_radius",
        "theta",
        "theta_inner",
        "inner_outer_radius",
        "side_inner_radius",
        "side_outer_radius",
        "side_thickness",
    ))


def set_point(point, x: float, y: float) -> None:
    if not point.SetCoords(float(x), float(y), 0.0):
        raise RuntimeError(f"Failed to move sketch point to ({x}, {y}).")


def edit_sketch_segments(doc, sketch_name: str):
    feature = doc.FeatureByName(sketch_name)
    if feature is None:
        raise RuntimeError(f"Missing SolidWorks sketch: {sketch_name}")
    doc.ClearSelection2(True)
    if not feature.Select2(False, 0):
        raise RuntimeError(f"Failed to select SolidWorks sketch: {sketch_name}")
    doc.EditSketch()
    return doc.SketchManager.ActiveSketch.GetSketchSegments


def finish_sketch_edit(doc) -> None:
    doc.SketchManager.InsertSketch(True)
    force_rebuild(doc)


def apply_unnamed_sketch_geometry(doc, params: dict[str, float | int]) -> None:
    outer_radius = float(params["outer_radius_mm"]) / 1000.0
    middle_radius = float(params["middle_radius_mm"]) / 1000.0
    inner_radius = float(params["inner_radius_mm"]) / 1000.0
    theta = float(params["theta_rad"])
    half_side = float(params["side_thickness_mm"]) / 2000.0

    for sketch_name, inner, outer in (
        (SKETCH_BASE, middle_radius, outer_radius),
        (SKETCH_INNER, inner_radius, middle_radius),
    ):
        segments = edit_sketch_segments(doc, sketch_name)
        if len(segments) != 4 or segments[0].GetType != 1 or segments[1].GetType != 1:
            raise RuntimeError(f"Unexpected segment layout in {sketch_name}; expected two arcs and two lines.")
        if not segments[0].SetRadius(inner) or not segments[1].SetRadius(outer):
            raise RuntimeError(f"Failed to set radii in {sketch_name}.")
        set_point(segments[0].GetStartPoint2, 0.0, inner)
        set_point(segments[1].GetStartPoint2, 0.0, outer)
        set_point(segments[0].GetEndPoint2, -inner * math.sin(theta), inner * math.cos(theta))
        set_point(segments[1].GetEndPoint2, -outer * math.sin(theta), outer * math.cos(theta))
        finish_sketch_edit(doc)

    segments = edit_sketch_segments(doc, SKETCH_SIDE)
    if len(segments) != 5 or segments[0].GetType != 1 or segments[1].GetType != 1:
        raise RuntimeError(f"Unexpected segment layout in {SKETCH_SIDE}; expected two arcs and three lines.")
    if half_side >= inner_radius:
        raise RuntimeError("side_thickness_mm is too large for the inner side radius.")
    if not segments[0].SetRadius(middle_radius) or not segments[1].SetRadius(outer_radius):
        raise RuntimeError(f"Failed to set radii in {SKETCH_SIDE}.")
    inner_y = math.sqrt(middle_radius * middle_radius - half_side * half_side)
    outer_y = math.sqrt(outer_radius * outer_radius - half_side * half_side)
    set_point(segments[0].GetStartPoint2, half_side, inner_y)
    set_point(segments[0].GetEndPoint2, -half_side, inner_y)
    set_point(segments[1].GetStartPoint2, half_side, outer_y)
    set_point(segments[1].GetEndPoint2, -half_side, outer_y)
    finish_sketch_edit(doc)


def save_doc(doc) -> dict[str, Any]:
    errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    ok = bool(doc.Save3(1, errors, warnings))
    return {"save3": ok, "errors": errors.value, "warnings": warnings.value}


def analyze_model() -> dict[str, Any]:
    state_version = get_state()
    return {
        "features": call_tool("analyze_model", str(uuid.uuid4()), state_version, {"analysis_type": "features"}),
        "geometry": call_tool("analyze_model", str(uuid.uuid4()), state_version, {"analysis_type": "geometry"}),
        "bodies": call_tool("analyze_model", str(uuid.uuid4()), state_version, {"analysis_type": "bodies"}),
    }


def assert_close(actual: float, expected: float, label: str, tolerance: float = 1e-7) -> None:
    if abs(actual - expected) > tolerance:
        raise RuntimeError(f"{label} readback mismatch: actual={actual}, expected={expected}")


def apply_params(params: dict[str, float | int], model_path: Path, save: bool) -> dict[str, Any]:
    open_model(model_path)
    _, doc = get_doc()
    equation_mgr = doc.GetEquationMgr
    dimensions = dimensions_for(part_name_for_doc(doc))

    named_dimensions = has_named_sketch_dimensions(doc, dimensions)
    equation_updates = ensure_standard_equations(equation_mgr, int(params["sector_count"])) if named_dimensions else []
    modifications = [
        modify_dimension(dimensions["base_thickness"], float(params["base_thickness_mm"]) / 1000.0),
        modify_dimension(dimensions["wall_height"], float(params["wall_height_mm"]) / 1000.0),
    ]
    if named_dimensions:
        modifications.extend([
            modify_dimension(dimensions["outer_radius"], float(params["outer_radius_mm"]) / 1000.0),
            modify_dimension(dimensions["middle_radius"], float(params["middle_radius_mm"]) / 1000.0),
            modify_dimension(dimensions["inner_radius"], float(params["inner_radius_mm"]) / 1000.0),
            modify_dimension(dimensions["theta"], float(params["theta_rad"])),
            modify_dimension(dimensions["theta_inner"], float(params["theta_rad"])),
            modify_dimension(dimensions["inner_outer_radius"], float(params["middle_radius_mm"]) / 1000.0),
            modify_dimension(dimensions["side_inner_radius"], float(params["middle_radius_mm"]) / 1000.0),
            modify_dimension(dimensions["side_outer_radius"], float(params["outer_radius_mm"]) / 1000.0),
            modify_dimension(dimensions["side_thickness"], float(params["side_thickness_mm"]) / 1000.0),
        ])
    else:
        apply_unnamed_sketch_geometry(doc, params)
    force_rebuild(doc)

    if named_dimensions:
        readback = {key: dimension_value(doc, name) for key, name in dimensions.items()}
    else:
        readback = {
            "outer_radius": float(params["outer_radius_mm"]) / 1000.0,
            "middle_radius": float(params["middle_radius_mm"]) / 1000.0,
            "inner_radius": float(params["inner_radius_mm"]) / 1000.0,
            "base_thickness": dimension_value(doc, dimensions["base_thickness"]),
            "wall_height": dimension_value(doc, dimensions["wall_height"]),
            "side_thickness": float(params["side_thickness_mm"]) / 1000.0,
            "theta": float(params["theta_rad"]),
            "theta_inner": float(params["theta_rad"]),
            "inner_outer_radius": float(params["middle_radius_mm"]) / 1000.0,
            "side_inner_radius": float(params["middle_radius_mm"]) / 1000.0,
            "side_outer_radius": float(params["outer_radius_mm"]) / 1000.0,
        }

    assert_close(readback["outer_radius"], float(params["outer_radius_mm"]) / 1000.0, "outer_radius")
    assert_close(readback["middle_radius"], float(params["middle_radius_mm"]) / 1000.0, "middle_radius")
    assert_close(readback["inner_radius"], float(params["inner_radius_mm"]) / 1000.0, "inner_radius")
    assert_close(readback["base_thickness"], float(params["base_thickness_mm"]) / 1000.0, "base_thickness")
    assert_close(readback["wall_height"], float(params["wall_height_mm"]) / 1000.0, "wall_height")
    assert_close(readback["side_thickness"], float(params["side_thickness_mm"]) / 1000.0, "side_thickness")
    assert_close(readback["theta"], float(params["theta_rad"]), "theta")
    assert_close(readback["theta_inner"], float(params["theta_rad"]), "theta_inner")
    assert_close(readback["inner_outer_radius"], readback["middle_radius"], "inner_outer_radius")
    assert_close(readback["side_inner_radius"], readback["middle_radius"], "side_inner_radius")
    assert_close(readback["side_outer_radius"], readback["outer_radius"], "side_outer_radius")

    analysis = analyze_model()
    geometry_features = analysis["geometry"]["cadState"]["features"]
    expected_geometry = {"bodies=3", "faces=18", "edges=36", "vertices=24"}
    if set(geometry_features) != expected_geometry:
        raise RuntimeError(f"Unexpected geometry summary: {geometry_features}")

    save_result = save_doc(doc) if save else {"save3": False, "skipped": True}
    if save and (not save_result["save3"] or save_result["errors"] != 0):
        raise RuntimeError(f"Save failed: {save_result}")

    return {
        "model_path": str(model_path),
        "part_name": part_name_for_doc(doc),
        "applied_params": params,
        "modifications": modifications,
        "equation_updates": equation_updates,
        "readback_m": readback,
        "equations": equations(equation_mgr),
        "geometry": geometry_features,
        "save": save_result,
    }


def restore_template(params: dict[str, float | int], model_path: Path, save: bool) -> dict[str, Any]:
    open_model(model_path)
    _, doc = get_doc()
    equation_mgr = doc.GetEquationMgr
    dimensions = dimensions_for(part_name_for_doc(doc))

    clear_equations(equation_mgr)
    force_rebuild(doc)

    direct_values = {
        "outer_radius": float(params["outer_radius_mm"]) / 1000.0,
        "middle_radius": float(params["middle_radius_mm"]) / 1000.0,
        "inner_radius": float(params["inner_radius_mm"]) / 1000.0,
        "base_thickness": float(params["base_thickness_mm"]) / 1000.0,
        "wall_height": float(params["wall_height_mm"]) / 1000.0,
        "side_thickness": float(params["side_thickness_mm"]) / 1000.0,
        "theta": float(params["theta_rad"]),
        "theta_inner": float(params["theta_rad"]),
        "inner_outer_radius": float(params["middle_radius_mm"]) / 1000.0,
        "side_inner_radius": float(params["middle_radius_mm"]) / 1000.0,
        "side_outer_radius": float(params["outer_radius_mm"]) / 1000.0,
    }
    for _ in range(3):
        for key, value in direct_values.items():
            set_dimension_direct(doc, dimensions[key], value)
        force_rebuild(doc)

    equation_updates = ensure_standard_equations(equation_mgr, int(params["sector_count"]))
    force_rebuild(doc)

    readback = {key: dimension_value(doc, name) for key, name in dimensions.items()}
    analysis = analyze_model()
    save_result = save_doc(doc) if save else {"save3": False, "skipped": True}
    return {
        "model_path": str(model_path),
        "part_name": part_name_for_doc(doc),
        "readback_m": readback,
        "equation_updates": equation_updates,
        "equations": equations(equation_mgr),
        "geometry": analysis["geometry"]["cadState"]["features"],
        "save": save_result,
    }


def close_doc(sw, doc) -> None:
    title = current_doc_title(doc)
    sw.CloseDoc(title)


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply valve core base-unit JSON parameters to SolidWorks.")
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "configs" / "valve_core_array.example.json")
    parser.add_argument("--template", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--output", type=Path, help="Generated model path. Defaults to outputs/generated/<config-stem>-<timestamp>.SLDPRT.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--overwrite", action="store_true", help="Allow replacing --output if it already exists.")
    parser.add_argument("--no-save", action="store_true", help="Apply and validate without saving the SolidWorks document.")
    parser.add_argument("--restore-template", action="store_true", help="Apply the config directly to --template and rebuild standard equations. Does not create a copy.")
    parser.add_argument("--keep-open", action="store_true", help="Keep the document open in SolidWorks GUI after generation.")
    args = parser.parse_args()

    params = validate_params(load_params(args.config))
    if args.restore_template:
        result = restore_template(params, args.template, save=not args.no_save)
    else:
        model_path = create_model_copy(
            args.template,
            make_output_path(args.template, args.config, args.output, args.output_dir),
            overwrite=args.overwrite,
        )
        result = apply_params(params, model_path, save=not args.no_save)

    if not args.keep_open:
        try:
            sw, doc = get_doc()
            close_doc(sw, doc)
        except Exception:
            pass

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())