import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import generate_valve_core_array as generator


class FakeDocument:
    def ForceRebuild3(self, _top_only):
        return True

    def GetBodies2(self, _body_type, _visible_only):
        return []


def test_full_generation_removes_temporary_top_cap(monkeypatch, tmp_path):
    config_path = tmp_path / "array.json"
    config_path.write_text(json.dumps({
        "unit_params": {
            "outer_diameter_mm": 80.0,
            "middle_radius_mm": 15.0,
            "inner_radius_mm": 13.5,
            "base_thickness_mm": 3.0,
            "wall_height_mm": 30.0,
            "side_thickness_mm": 1.5,
        },
        "array_params": {"layer_count": 1, "sector_count": 6},
    }), encoding="utf-8")
    base_model = tmp_path / "base.SLDPRT"
    top_cap_model = tmp_path / "cap.SLDPRT"
    output_model = tmp_path / "result.SLDPRT"
    base_model.touch()
    top_cap_model.touch()
    document = FakeDocument()
    prepared_paths = []
    closed_documents = []

    monkeypatch.setattr(generator, "create_model_copy", lambda _source, target, overwrite: target)
    monkeypatch.setattr(generator, "apply_params", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(generator, "get_doc", lambda: (object(), document))
    monkeypatch.setattr(generator, "close_doc", lambda _sw, doc: closed_documents.append(doc))
    monkeypatch.setattr(generator, "create_circular_pattern", lambda *_args: "circular")
    monkeypatch.setattr(generator, "identify_and_map_bodies", lambda *_args: [])
    monkeypatch.setattr(generator, "save_active_doc", lambda _doc: {"save3": True, "errors": 0, "warnings": 0})

    def prepare_top_cap(**kwargs):
        path = kwargs["output_cap_path"]
        path.touch()
        prepared_paths.append(path)
        return path

    def insert_top_cap(_doc, path, _height):
        assert path.is_file()
        return "move-cap"

    monkeypatch.setattr(generator, "prepare_top_cap_model", prepare_top_cap)
    monkeypatch.setattr(generator, "insert_and_position_top_cap", insert_top_cap)

    result = generator.execute_full_array_generation(
        config_path=config_path,
        output_path=output_model,
        base_model_path=base_model,
        top_cap_model_path=top_cap_model,
    )

    assert result["status"] == "COMPLETED"
    assert result["top_cap_feature"] == "move-cap"
    assert len(prepared_paths) == 1
    assert not prepared_paths[0].exists()
    assert list(tmp_path.glob("*_top_cap.SLDPRT")) == []
    assert closed_documents == [document]