import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import solidworks_array_execute as swe


def test_build_tasks_and_report():
    payload = {
        "manifest": [
            {"logical_id": "L1_S1_base", "layer": 1, "sector": 1, "body_type": "base", "angle_deg": 0.0, "translation_mm": [0.0, 0.0, 0.0]},
            {"logical_id": "L1_S2_base", "layer": 1, "sector": 2, "body_type": "base", "angle_deg": 90.0, "translation_mm": [0.0, 0.0, 0.0]},
        ],
        "delete_manifest": [{"logical_id": "L1_S2_base"}],
    }

    tasks = swe.build_tasks(payload)

    assert len(tasks) == 2
    assert tasks[1]["status"] == "pending"
    assert tasks[1]["logical_id"] == "L1_S2_base"


def test_assign_real_bodies_and_delete_targets():
    real_bodies = [
        {"name": "Body-A", "center": [0.0, 0.0, 0.0]},
        {"name": "Body-B", "center": [1.0, 0.0, 0.0]},
    ]
    manifest = [
        {"logical_id": "L1_S1_base", "layer": 1, "sector": 1, "body_type": "base"},
        {"logical_id": "L1_S2_base", "layer": 1, "sector": 2, "body_type": "base"},
    ]
    delete_manifest = [{"logical_id": "L1_S2_base", "name": "Body-B"}]

    assigned = swe.assign_real_bodies_to_manifest(real_bodies, manifest)
    targets = swe.map_delete_targets(assigned, delete_manifest)

    assert assigned[1]["logical_id"] == "L1_S2_base"
    assert targets == ["Body-B"]


def test_main_writes_report(tmp_path):
    payload = {
        "manifest": [
            {"logical_id": "L1_S1_base", "layer": 1, "sector": 1, "body_type": "base", "angle_deg": 0.0, "translation_mm": [0.0, 0.0, 0.0]},
            {"logical_id": "L1_S2_base", "layer": 1, "sector": 2, "body_type": "base", "angle_deg": 90.0, "translation_mm": [0.0, 0.0, 0.0]},
        ],
        "delete_manifest": [{"logical_id": "L1_S2_base"}],
    }
    in_path = tmp_path / "payload.json"
    in_path.write_text(json.dumps(payload), encoding="utf-8")

    out_path = tmp_path / "report.json"
    result = swe.load_execution_payload(in_path)
    assert result["manifest"][1]["logical_id"] == "L1_S2_base"
    assert len(result["delete_manifest"]) == 1
