import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import build_array_model as bam


def test_generate_array_plan_counts_entities():
    config = {
        "layer_count": 2,
        "sector_count": 4,
        "layer_pitch_mm": 20.0,
        "body_types": ["base", "inner", "side"],
    }

    plan = bam.generate_array_plan(config)

    assert plan["total_entities"] == 24
    assert plan["angle_step_deg"] == 90.0
    assert plan["manifest"][0]["logical_id"] == "L1_S1_base"
    assert plan["manifest"][-1]["logical_id"] == "L2_S4_side"


def test_apply_delete_selection_keeps_only_requested_ids():
    plan = bam.generate_array_plan({
        "layer_count": 1,
        "sector_count": 3,
        "layer_pitch_mm": 10.0,
        "body_types": ["base", "inner", "side"],
    })

    plan = bam.apply_delete_selection(plan, ["L1_S2_inner"])

    assert len(plan["delete_manifest"]) == 1
    assert plan["delete_manifest"][0]["logical_id"] == "L1_S2_inner"


def test_write_plan_json(tmp_path):
    config = {
        "layer_count": 1,
        "sector_count": 3,
        "layer_pitch_mm": 15.0,
        "body_types": ["base", "inner", "side"],
    }

    output_path = tmp_path / "plan.json"
    result = bam.write_plan_json(bam.generate_array_plan(config), output_path)

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["total_entities"] == 9
    assert result["delete_manifest"] == []


def test_assign_logical_ids_to_real_bodies():
    config = {
        "layer_count": 2,
        "sector_count": 4,
        "layer_pitch_mm": 20.0,
        "body_types": ["base", "inner", "side"],
    }

    bodies = [
        {"name": "Body1", "center": [0.0, 0.0, 0.0], "body_type": "base"},
        {"name": "Body2", "center": [10.0, 0.0, 0.0], "body_type": "inner"},
        {"name": "Body3", "center": [14.0, 0.0, 0.0], "body_type": "side"},
        {"name": "Body4", "center": [0.0, 0.0, 20.0], "body_type": "base"},
    ]

    result = bam.assign_logical_ids_to_bodies(bodies, config)

    assert result[0]["logical_id"] == "L1_S1_base"
    assert result[1]["logical_id"] == "L1_S1_inner"
    assert result[2]["logical_id"] == "L1_S1_side"
    assert result[3]["logical_id"] == "L1_S2_base"


def test_build_delete_targets_from_real_body_names():
    bodies = [
        {"name": "Body-1", "logical_id": "L1_S1_base"},
        {"name": "Body-2", "logical_id": "L1_S2_inner"},
        {"name": "Body-3", "logical_id": "L1_S3_side"},
    ]

    delete_targets = bam.build_delete_targets(bodies, ["L1_S2_inner"])

    assert delete_targets == ["Body-2"]
    assert len(delete_targets) == 1
