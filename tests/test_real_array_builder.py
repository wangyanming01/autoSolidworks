import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import real_array_builder as rab


def test_build_execution_plan_generates_steps():
    config = {
        "layer_count": 1,
        "sector_count": 3,
        "layer_pitch_mm": 10.0,
        "body_types": ["base", "inner", "side"],
    }

    plan = rab.build_execution_plan(config, ["L1_S2_inner"])

    assert plan["total_entities"] == 9
    assert len(plan["steps"]) == 9
    assert plan["steps"][4]["logical_id"] == "L1_S2_inner"
    assert plan["delete_manifest"][0]["logical_id"] == "L1_S2_inner"


def test_write_execution_plan_json(tmp_path):
    config = {
        "layer_count": 1,
        "sector_count": 3,
        "layer_pitch_mm": 15.0,
        "body_types": ["base", "inner", "side"],
    }

    output = tmp_path / "exec-plan.json"
    result = rab.write_execution_plan_json(config, output, ["L1_S1_base"])

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["total_entities"] == 9
    assert len(payload["delete_manifest"]) == 1
    assert result["steps"][0]["action"] == "generate_body"
