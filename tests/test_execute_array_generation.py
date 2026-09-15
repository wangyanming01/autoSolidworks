import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import execute_array_generation as eag


def test_build_execution_payload_basic():
    config = {
        "layer_count": 1,
        "sector_count": 3,
        "layer_pitch_mm": 10.0,
        "body_types": ["base", "inner", "side"],
    }

    payload = eag.build_execution_payload(config, ["L1_S2_inner"])

    assert payload["total_entities"] == 9
    assert payload["delete_count"] == 1
    assert payload["steps"][4]["logical_id"] == "L1_S2_inner"


def test_write_execution_payload(tmp_path):
    config = {
        "layer_count": 1,
        "sector_count": 3,
        "layer_pitch_mm": 5.0,
        "body_types": ["base", "inner", "side"],
    }

    output = tmp_path / "exec.json"
    payload = eag.write_execution_payload(config, output, ["L1_S3_side"])

    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["delete_count"] == 1
    assert payload["steps"][8]["logical_id"] == "L1_S3_side"
