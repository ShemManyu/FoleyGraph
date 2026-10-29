import copy

import pytest

from server.director import normalize_analysis


def test_ai_proposals_clamp_boxes_snap_times_and_keep_distinct_instances(scene):
    proposal = {
        "objects": [
            {
                "id": "a",
                "name": "First walker",
                "profile": "metal",
                "keyframes": [
                    {"time": -0.5, "x": 0.9, "y": 0.8, "width": 0.3, "height": 0.5},
                    {"time": 8, "x": 0.7, "y": 0.4, "width": 0.1, "height": 0.3, "visible": False},
                ],
            },
            {"id": "b", "name": "Second walker", "profile": "soft", "keyframes": []},
        ],
        "cues": [
            {"object_id": "a", "kind": "footstep", "time": 0.42, "duration": 0.26},
            {"object_id": "b", "kind": "footstep", "time": 1.1, "duration": 0.26},
            {"object_id": "a", "kind": "impact", "time": 8},
            {"object_id": "unknown", "kind": "impact", "time": 2},
        ],
    }
    after = normalize_analysis(scene, proposal, "Two different characters")
    assert len(after.objects) == 2
    assert len(after.cues) == 2
    assert after.cues[0].object_id != after.cues[1].object_id
    assert after.cues[0].time == pytest.approx(10 / 24)
    assert after.cues[0].asset_id == "metal-footstep"
    assert after.objects[0].keyframes[-1].time == 4
    assert after.objects[0].keyframes[-1].visible is False
    first_box = after.objects[0].keyframes[0]
    assert first_box.x + first_box.width == pytest.approx(1)
    assert first_box.y + first_box.height == pytest.approx(1)
    assert scene.cues[0].asset_id == "wood-footstep"
    ambiguous = copy.deepcopy(proposal)
    ambiguous["objects"][1]["id"] = "a"
    with pytest.raises(ValueError, match="ambiguous"):
        normalize_analysis(scene, ambiguous, "A scene")


def test_empty_or_nonfinite_ai_output_is_not_silently_reported_as_success(scene):
    with pytest.raises(ValueError, match="incomplete"):
        normalize_analysis(scene, {}, "A scene")
    with pytest.raises(ValueError, match="numeric"):
        normalize_analysis(
            scene,
            {"objects": [{"id": "a", "keyframes": [{"time": float("nan")}]}], "cues": []},
            "A scene",
        )
