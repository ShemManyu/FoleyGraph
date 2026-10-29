import numpy as np
import pytest

from server.audio import render_layers, wav_bytes
from server.models import Asset, CueCreate, CuePatch, EditRequest, Operation, ProjectPatch
from server.storage import Conflict


def test_selective_material_preserves_untargeted_pcm_and_timing(studio, scene, library):
    baseline = render_layers(scene, library)
    after = studio.edit(
        "owner",
        scene.id,
        EditRequest(
            revision=0,
            object_id="left",
            operations=[Operation(type="set_sound", profile="metal", kind="footstep")],
        ),
    )
    changed = render_layers(after, library)
    assert wav_bytes(baseline["right"]) == wav_bytes(changed["right"])
    assert wav_bytes(baseline["prop"]) == wav_bytes(changed["prop"])
    assert wav_bytes(baseline["left"]) != wav_bytes(changed["left"])
    assert [(cue.id, cue.time, cue.duration) for cue in after.cues] == [
        (cue.id, cue.time, cue.duration) for cue in scene.cues
    ]
    assert after.cues[2] == scene.cues[2]
    assert [cue.asset_id for cue in after.cues[:2]] == ["metal-footstep", "metal-footstep"]
    assert after.cues[3:] == scene.cues[3:]


def test_invalid_cross_object_tool_call_is_atomic(studio, scene):
    with pytest.raises(ValueError, match="another object's"):
        studio.edit(
            "owner",
            scene.id,
            EditRequest(
                revision=0,
                object_id="left",
                operations=[
                    Operation(type="gain", value=-10),
                    Operation(type="set_sound", profile="metal", cue_ids=["right-step"]),
                ],
            ),
        )
    assert studio.get("owner", scene.id) == scene


def test_stale_edit_cannot_overwrite_and_undo_advances_revision(studio, scene):
    edited = studio.patch_cue("owner", scene.id, "left-step-1", CuePatch(revision=0, time=0.42))
    assert edited.cues[0].time == pytest.approx(10 / 24)
    with pytest.raises(Conflict):
        studio.patch_project("owner", scene.id, ProjectPatch(revision=0, name="Stale title"))
    restored = studio.undo("owner", scene.id, edited.revision)
    assert restored.cues == scene.cues
    assert restored.revision == 2
    assert restored.undo_revisions == []


def test_undo_keeps_referenced_snapshots_after_branching(studio, scene):
    current = scene
    for index in range(20):
        current = studio.patch_project(
            "owner", scene.id, ProjectPatch(revision=current.revision, name=f"First {index}")
        )
    for _ in range(15):
        current = studio.undo("owner", scene.id, current.revision)
    for index in range(18):
        current = studio.patch_project(
            "owner", scene.id, ProjectPatch(revision=current.revision, name=f"Branch {index}")
        )
    for _ in range(20):
        current = studio.undo("owner", scene.id, current.revision)
    assert current.name == "First 2"
    assert not current.undo_revisions


def test_frame_shift_clamps_at_clip_bounds_and_does_not_move_other_cues(studio, scene):
    after = studio.edit(
        "owner",
        scene.id,
        EditRequest(
            revision=0,
            object_id="left",
            cue_id="left-step-1",
            operations=[Operation(type="shift", frames=-120)],
        ),
    )
    assert after.cues[0].time == 0
    assert after.cues[1:] == scene.cues[1:]
    with pytest.raises(ValueError):
        studio.patch_cue(
            "owner", scene.id, "left-step-1", CuePatch(revision=after.revision, duration=5)
        )
    assert studio.get("owner", scene.id).revision == after.revision


def test_visibility_never_emits_audio_without_an_explicit_action(scene, library):
    scene.cues = []
    layers = render_layers(scene, library)
    assert len(layers) == 3
    assert all(not np.any(layer) for layer in layers.values())


def test_custom_sound_identity_is_reused_by_future_actions(studio, scene, library):
    assets = library.data_dir / "media" / scene.id / "assets"
    assets.mkdir(parents=True)
    (assets / "user_tap.wav").write_bytes((library.samples_dir / "glass-impact.wav").read_bytes())
    with_asset = scene.model_copy(deep=True)
    with_asset.assets.append(Asset(id="user_tap", name="My tap", duration=0.65))
    current = studio.commit("owner", scene, with_asset)
    current = studio.edit(
        "owner",
        scene.id,
        EditRequest(
            revision=current.revision,
            object_id="left",
            operations=[Operation(type="set_sound", asset_id="user_tap", kind="footstep")],
        ),
    )
    after = studio.add_cue(
        "owner",
        scene.id,
        CueCreate(revision=current.revision, object_id="left", kind="footstep", time=3),
    )
    assert after.cues[-1].asset_id == "user_tap"
    assert after.cues[-1].duration == 0.65
    assert after.cues[2] == scene.cues[2]
    assert after.cues[3:5] == scene.cues[3:5]
