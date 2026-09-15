import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import build_array_manifest as bam


def test_build_manifest_counts_and_ids():
    config = {
        "layer_count": 2,
        "sector_count": 4,
        "layer_pitch_mm": 20.0,
        "body_types": ["base", "inner", "side"],
    }

    manifest = bam.build_manifest(config)

    assert len(manifest) == 2 * 4 * 3
    assert manifest[0]["logical_id"] == "L1_S1_base"
    assert manifest[-1]["logical_id"] == "L2_S4_side"
    assert manifest[3]["angle_deg"] == 90.0
    assert manifest[3]["translation_mm"][2] == 0.0


def test_build_delete_manifest_filters_requested_items():
    manifest = [
        {"logical_id": "L1_S1_base", "layer": 1, "sector": 1, "body_type": "base"},
        {"logical_id": "L1_S1_inner", "layer": 1, "sector": 1, "body_type": "inner"},
        {"logical_id": "L1_S2_side", "layer": 1, "sector": 2, "body_type": "side"},
    ]

    delete_manifest = bam.build_delete_manifest(manifest, ["L1_S1_inner", "L1_S2_side"])

    assert [item["logical_id"] for item in delete_manifest] == ["L1_S1_inner", "L1_S2_side"]
    assert len(delete_manifest) == 2


def test_validate_config_rejects_invalid_sector_count():
    try:
        bam.validate_config({"layer_count": 2, "sector_count": 2, "layer_pitch_mm": 10.0})
        raise AssertionError("Expected ValueError for sector_count < 3")
    except ValueError:
        pass


def test_write_manifest_json(tmp_path):
    config = {
        "layer_count": 1,
        "sector_count": 3,
        "layer_pitch_mm": 15.0,
    }

    output_path = tmp_path / "manifest.json"
    bam.write_manifest_json(config, output_path)

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(payload["manifest"]) == 9
    assert payload["delete_manifest"] == []
