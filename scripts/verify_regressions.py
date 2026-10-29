"""Verify that isolation and surface regressions reject deliberately broken edits."""

import inspect
import sys
import textwrap
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server.director as director_module  # noqa: E402
import server.main as main_module  # noqa: E402
import server.segmentation as segmentation_module  # noqa: E402
import server.studio as studio_module  # noqa: E402
import server.visual as visual_module  # noqa: E402
from scripts import deploy as deploy_module  # noqa: E402
from scripts import prepare_meta_model as preparation_module  # noqa: E402


def main():
    clothing_test = (
        "tests/test_scene_edits.py::"
        "test_off_white_clothing_recolors_across_lighting_without_changing_the_other_person"
    )
    cases = (
        (
            main_module,
            main_module,
            "create_app",
            "key = (owner(request), job_id)",
            'key = next((key for key in edit_jobs if key[1] == job_id), ("", ""))',
            "tests/test_scene_edits.py::test_async_edit_returns_before_work_finishes_and_is_private_and_exclusive",
            "exposing a processing receipt to another workspace",
        ),
        (
            main_module,
            main_module,
            "create_app",
            'heavy_lock.release()\n\n    @app.get("/api/jobs/{job_id}")',
            'pass\n\n    @app.get("/api/jobs/{job_id}")',
            "tests/test_scene_edits.py::test_async_failures_preserve_the_scene_and_release_processing_capacity",
            "leaking the processing permit after a background failure",
        ),
        (
            visual_module,
            visual_module.RecolorTrack,
            "apply",
            'if self.effect.surface_kind == "fabric":',
            "if True:",
            "tests/test_scene_edits.py::test_meta_fabric_disocclusion_recovers_color_but_object_holes_stay_excluded",
            "filling deliberately unselected holes in an object mask",
        ),
        (
            visual_module,
            visual_module.RecolorTrack,
            "apply",
            "self.model_mask = tracking_envelope(self.model_mask)",
            "pass",
            "tests/test_scene_edits.py::test_meta_fabric_disocclusion_recovers_color_but_object_holes_stay_excluded",
            "leaving an occluder's old hole in newly revealed clothing",
        ),
        (
            segmentation_module,
            segmentation_module,
            "predict_mask",
            "_encode_image(image.tobytes(), size, model_sha256)",
            "_encode_image.__wrapped__(image.tobytes(), size, model_sha256)",
            "tests/test_segmentation.py::test_encoder_reuses_only_identical_source_and_model_but_rechecks_each_prompt",
            "re-encoding unchanged source pixels for every follow-up edit",
        ),
        (
            segmentation_module,
            segmentation_module,
            "predict_mask",
            "_encode_image(image.tobytes(), size, model_sha256)",
            '_encode_image(image.tobytes(), size, "a" * 64)',
            "tests/test_segmentation.py::test_encoder_reuses_only_identical_source_and_model_but_rechecks_each_prompt",
            "sharing image encodings across different model identities",
        ),
        (
            visual_module,
            visual_module,
            "prepare_preview",
            "300 if uses_meta else 120",
            "180 if uses_meta else 120",
            "tests/test_scene_edits.py::test_meta_cpu_budget_allows_measured_work_but_remains_bounded",
            "aborting long Meta work at the old synchronous deadline",
        ),
        (
            visual_module,
            visual_module,
            "prepare_preview",
            "300 if uses_meta else 120",
            "1000000",
            "tests/test_scene_edits.py::test_meta_cpu_budget_allows_measured_work_but_remains_bounded",
            "removing the Meta and CV render deadlines",
        ),
        (
            segmentation_module,
            segmentation_module,
            "predict_mask",
            'size = info["input_size"]',
            "size = INPUT_SIZE",
            "tests/test_segmentation.py::test_predictor_uses_installed_bundle_resolution",
            "feeding the wrong image and prompt resolution to an installed Meta bundle",
        ),
        (
            preparation_module,
            preparation_module,
            "download",
            "time.monotonic() + 900",
            "time.monotonic() + 300",
            "tests/test_segmentation.py::test_slow_model_download_can_finish_but_still_has_a_deadline",
            "aborting a valid active model download on a slow connection",
        ),
        (
            segmentation_module,
            segmentation_module,
            "refine_tracked_mask",
            ">= 0.95",
            "> 0",
            "tests/test_segmentation.py::test_tracking_refinement_only_adds_nearby_pixels_of_already_supported_components",
            "growing a learned mask into a poorly supported neighboring surface",
        ),
        (
            segmentation_module,
            segmentation_module,
            "propagate_mask",
            "backward[:, :, 0] *= width / size[0]",
            "backward[:, :, 0] *= 1",
            "tests/test_segmentation.py::test_mask_propagation_follows_local_motion_in_the_correct_direction_and_scale",
            "losing full-resolution movement while propagating a Meta mask",
        ),
        (
            visual_module,
            visual_module.RecolorTrack,
            "apply",
            "or timestamp - self.model_timestamp >= 1",
            "or False",
            "tests/test_scene_edits.py::test_meta_mask_constrains_the_render_without_inference_on_every_frame",
            "letting a sparse anchor mask drift throughout a changing shot",
        ),
        (
            visual_module,
            visual_module.RecolorTrack,
            "apply",
            "excluded |= self.model_mask == 0",
            "excluded |= False",
            "tests/test_scene_edits.py::test_meta_mask_constrains_the_render_without_inference_on_every_frame",
            "tagging an edit as Meta-backed without using its learned mask",
        ),
        (
            visual_module,
            visual_module,
            "prepare_preview",
            "source_frame=source_frame",
            "source_frame=frame",
            "tests/test_scene_edits.py::test_meta_render_samples_original_pixels_before_other_edits",
            "feeding a previous recolor into the next Meta segmentation",
        ),
        (
            segmentation_module,
            segmentation_module,
            "predict_mask",
            "scores[0, 0] < 0.7",
            "False",
            "tests/test_segmentation.py::test_predictor_rejects_bad_confidence_and_protected_points",
            "accepting a low-confidence Meta mask",
        ),
        (
            segmentation_module,
            segmentation_module,
            "refine_mask",
            "mask |= fill[labels].astype(np.uint8)",
            "pass",
            "tests/test_segmentation.py::test_mask_refinement_fills_small_clothing_holes_without_crossing_the_target",
            "leaving small navy holes in an otherwise recolored garment",
        ),
        (
            deploy_module,
            deploy_module,
            "readiness",
            'status.get("backend_revision") == expected_revision',
            "True",
            "tests/test_deploy.py::test_readiness_rejects_a_healthy_old_worker_before_accepting_the_new_source",
            "mistaking a healthy old worker for the new deployment",
        ),
        (
            visual_module,
            visual_module,
            "color_mask",
            "saturation > (0.12 if strong else 0.08)",
            "saturation > max(0.12, float(source_saturation) * (0.6 if strong else 0.45))",
            "tests/test_scene_edits.py::test_real_stock_clothing_is_not_fragmented_by_a_plausible_model_color",
            "turning a small model color difference into a patchy real-stock outfit edit",
        ),
        (
            visual_module,
            visual_module,
            "color_mask",
            "brightness = np.minimum(1, lightness / max(0.05, float(source_lightness)))",
            "brightness = np.ones_like(lightness)",
            "tests/test_scene_edits.py::test_dark_blue_fabric_folds_remain_one_visible_garment_surface",
            "splitting a dark fabric fold into an unselected blue panel",
        ),
        (
            visual_module,
            visual_module.RecolorTrack,
            "_snap_surface",
            "margin = max(2, round(min(width, height) * 0.08))",
            "margin = 2",
            "tests/test_scene_edits.py::test_clothing_at_the_frame_edge_is_recolored_without_touching_the_other_person",
            "clipping the real garment to an approximate tracked bounding box",
        ),
        (
            visual_module,
            visual_module.RecolorTrack,
            "apply",
            "matte[selected] = 1",
            "pass",
            "tests/test_scene_edits.py::test_clothing_at_the_frame_edge_is_recolored_without_touching_the_other_person",
            "blending the original clothing color back into selected boundary pixels",
        ),
        (
            visual_module,
            visual_module,
            "color_mask",
            "chroma > threshold",
            "np.ones_like(chroma, dtype=bool)",
            "tests/test_scene_edits.py::test_pale_face_is_not_proposed_as_a_saturated_painted_body",
            "mistaking a pale face for a saturated painted body",
        ),
        (
            director_module,
            director_module,
            "surface_reference",
            "key=lambda index: np.linalg.norm(centers[index] / [width, height] - center)",
            "key=lambda index: -stats[index, cv2.CC_STAT_AREA]",
            "tests/test_scene_edits.py::test_small_target_is_not_crowded_out_by_large_background_regions",
            "large background regions crowding out the requested small surface",
        ),
        (
            director_module,
            director_module,
            "surface_reference",
            (
                "left, top = np.minimum(bounds[:, :2].min(axis=0), np.floor(focus.min(axis=0)).astype(int))",
                "right, bottom = np.maximum(\n"
                "        (bounds[:, :2] + bounds[:, 2:]).max(axis=0), np.ceil(focus.max(axis=0)).astype(int) + 1\n"
                "    )",
            ),
            (
                "left, top = bounds[:, :2].min(axis=0)",
                "right, bottom = (bounds[:, :2] + bounds[:, 2:]).max(axis=0)",
            ),
            "tests/test_scene_edits.py::test_nearby_small_highlights_do_not_crop_away_the_main_target_surface",
            "cropping away the main target when two small highlights are closest to its center",
        ),
        (
            visual_module,
            visual_module.RecolorTrack,
            "_surface_mask",
            (
                "height, width = guide.shape",
                "return (keep[components] | (guide > 0)) & matching & ~excluded",
            ),
            (
                "mask[0, :] = mask[-1, :] = mask[:, 0] = mask[:, -1] = cv2.GC_BGD\n"
                "    height, width = guide.shape",
                "return keep[components] & matching",
            ),
            "tests/test_scene_edits.py::test_clothing_at_the_frame_edge_is_recolored_without_touching_the_other_person",
            "leaving an uncolored garment stripe at the frame edge",
        ),
        (
            studio_module,
            studio_module.Studio,
            "apply_edit",
            "if cue.object_id == request.object_id",
            "if True",
            "tests/test_studio.py::test_selective_material_preserves_untargeted_pcm_and_timing",
            "a global edit of another character's PCM",
        ),
        (
            visual_module,
            visual_module.RecolorTrack,
            "_snap_surface",
            "excluded = (strong > 0) & ~selected",
            "selected = strong > 0\n    excluded = np.zeros_like(guide, dtype=bool)",
            clothing_test,
            "recoloring the other person's matching shirt",
        ),
        (
            visual_module,
            visual_module.RecolorTrack,
            "_snap_surface",
            "selected = labels == chosen",
            "selected = guide > 0",
            clothing_test,
            "trusting a misplaced model polygon instead of the visible garment",
        ),
        (
            visual_module,
            visual_module.RecolorTrack,
            "_snap_surface",
            "selected &= inside > 0",
            "selected |= labels > 0",
            "tests/test_scene_edits.py::test_touching_same_color_saucer_is_not_recolored_with_the_cup",
            "recoloring a touching same-color saucer along with the cup",
        ),
        (
            visual_module,
            visual_module,
            "surface_components",
            "cv2.Canny(gray, low, high)",
            "cv2.Canny(gray, 15, 45)",
            "tests/test_scene_edits.py::test_subtle_contact_edge_separates_a_white_cup_from_its_white_saucer",
            "merging a pale cup with its saucer across a subtle contact boundary",
        ),
        (
            visual_module,
            visual_module,
            "surface_components",
            "if split_edges:",
            "if True:",
            "tests/test_scene_edits.py::test_fabric_folds_do_not_split_one_shirt_into_partial_color_patches",
            "splitting a folded shirt into a small recolored patch",
        ),
        (
            visual_module,
            visual_module,
            "color_mask",
            "matching = (saturation < 0.3) | (chroma < 0.12)",
            "matching = saturation < 0.3",
            clothing_test,
            "misclassifying clipped white fabric as a saturated color",
        ),
    )
    for module, owner, name, anchor, replacement, test, description in cases:
        original = getattr(owner, name)
        source = textwrap.dedent(inspect.getsource(original))
        anchors = (anchor,) if isinstance(anchor, str) else anchor
        replacements = (replacement,) if isinstance(replacement, str) else replacement
        buggy = source
        for before, after in zip(anchors, replacements, strict=True):
            if buggy.count(before) != 1:
                raise RuntimeError("The mutation anchor changed; update this regression check.")
            buggy = buggy.replace(before, after, 1)
        namespace = dict(vars(module))
        exec(compile(buggy, "<intentional-regression-mutation>", "exec"), namespace)
        compiled = namespace[name]
        mutant = types.FunctionType(
            compiled.__code__, vars(module), name, compiled.__defaults__, compiled.__closure__
        )
        mutant.__kwdefaults__ = compiled.__kwdefaults__
        try:
            setattr(owner, name, mutant)
            result = pytest.main(["-q", "--tb=short", "--assert=plain", test])
            if result != 1:
                raise RuntimeError(f"The regression test did not catch {description}: {result}")
            print(f"PASS: the regression rejects {description}.")
        finally:
            setattr(owner, name, original)


if __name__ == "__main__":
    main()
