import hashlib
import io
import json
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from scripts import prepare_meta_model as preparation_module
from server import segmentation


@pytest.mark.parametrize("elapsed", [350, 950])
def test_slow_model_download_can_finish_but_still_has_a_deadline(tmp_path, monkeypatch, elapsed):
    payload = b"reviewed model bytes"
    ticks = iter([0, elapsed])
    monkeypatch.setattr(preparation_module, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    monkeypatch.setattr(
        preparation_module.urllib.request,
        "urlopen",
        lambda *args, **kwargs: io.BytesIO(payload),
    )
    target = tmp_path / "model.onnx"
    expected = hashlib.sha256(payload).hexdigest()
    if elapsed < 900:
        preparation_module.download("https://example.invalid/model", target, expected)
        assert target.read_bytes() == payload
    else:
        with pytest.raises(RuntimeError, match="size or time limit"):
            preparation_module.download("https://example.invalid/model", target, expected)


@pytest.fixture
def prepared_model(tmp_path, monkeypatch):
    directory = tmp_path / "model"
    directory.mkdir()
    files = {}
    for name in ("encoder.onnx", "decoder.onnx"):
        payload = name.encode()
        (directory / name).write_bytes(payload)
        files[name] = hashlib.sha256(payload).hexdigest()
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "model": segmentation.MODEL_NAME,
                "input_size": segmentation.INPUT_SIZE,
                "checkpoint_sha256": segmentation.CHECKPOINT_SHA256,
                "source_revision": segmentation.SOURCE_REVISION,
                "files": files,
            }
        )
    )
    monkeypatch.setattr(segmentation, "MODEL_DIR", directory)
    segmentation.model_info.cache_clear()
    segmentation._encode_image.cache_clear()
    yield directory
    segmentation.model_info.cache_clear()
    segmentation._encode_image.cache_clear()


@pytest.mark.parametrize("filename", ["encoder.onnx", "decoder.onnx"])
def test_corrupt_model_is_rejected_before_inference(prepared_model, filename):
    (prepared_model / filename).write_bytes(b"not the reviewed model")
    with pytest.raises(ValueError, match="Meta mask model is unavailable"):
        segmentation.model_info()


@pytest.mark.parametrize("input_size", [512, 768])
def test_predictor_uses_installed_bundle_resolution(prepared_model, monkeypatch, input_size):
    manifest = prepared_model / "manifest.json"
    data = json.loads(manifest.read_text())
    data["input_size"] = input_size
    manifest.write_text(json.dumps(data))
    tensors, prompts = [], []
    logits = np.full((1, 1, 240, 320), -1, np.float32)
    logits[:, :, 84:173, 208:272] = 1

    def encode(_, inputs):
        tensors.append(inputs["image"])
        return [np.zeros((1, 1), np.float32)] * 3

    def decode(_, inputs):
        prompts.append(inputs["coordinates"])
        return logits, np.array([[0.95]], np.float32)

    monkeypatch.setattr(
        segmentation,
        "_sessions",
        lambda: (SimpleNamespace(run=encode), SimpleNamespace(run=decode)),
    )
    result = segmentation.predict_mask(
        np.full((240, 320, 3), 100, np.uint8),
        np.array([[208, 84], [272, 84], [272, 173], [208, 173]], np.float32),
        np.array([[0.75, 0.54]], np.float32),
        np.array([[0.25, 0.54]], np.float32),
        (logits[0, 0] > 0).astype(np.uint8) * 255,
        segmentation.model_info()["sha256"],
    )
    assert tensors[0].shape == (1, 3, input_size, input_size)
    np.testing.assert_allclose(prompts[0][0, 2], np.array([0.75, 0.54]) * input_size)
    assert result[125, 220] == 255 and result[129, 80] == 0


def test_encoder_reuses_only_identical_source_and_model_but_rechecks_each_prompt(
    prepared_model, monkeypatch
):
    logits = np.full((1, 1, 240, 320), -1, np.float32)
    logits[:, :, 84:173, 208:272] = 1
    encoder = Mock(return_value=[np.zeros((1, 1), np.float32)] * 3)
    decoder = Mock(return_value=(logits, np.array([[0.95]], np.float32)))
    monkeypatch.setattr(
        segmentation,
        "_sessions",
        lambda: (SimpleNamespace(run=encoder), SimpleNamespace(run=decoder)),
    )
    info = segmentation.model_info()
    image = np.full((240, 320, 3), 100, np.uint8)
    polygon = np.array([[208, 84], [272, 84], [272, 173], [208, 173]], np.float32)

    def predict(protected):
        return segmentation.predict_mask(
            image,
            polygon,
            np.array([[0.75, 0.54]], np.float32),
            np.array([protected], np.float32),
            (logits[0, 0] > 0).astype(np.uint8) * 255,
            info["sha256"],
        )

    assert predict([0.25, 0.54])[125, 220] == 255
    with pytest.raises(ValueError, match="protect the surrounding surfaces"):
        predict([0.75, 0.54])
    assert encoder.call_count == 1 and decoder.call_count == 2
    image[0, 0] = 0
    predict([0.25, 0.54])
    assert encoder.call_count == 2
    info = {**info, "sha256": "b" * 64}
    with monkeypatch.context() as changed_model:
        changed_model.setattr(segmentation, "model_info", lambda: info)
        predict([0.25, 0.54])
    assert encoder.call_count == 3 and decoder.call_count == 4


@pytest.mark.parametrize(
    ("score", "protected_hit"),
    [(0.4, False), (0.95, True)],
    ids=["low-confidence", "protected"],
)
def test_predictor_rejects_bad_confidence_and_protected_points(
    prepared_model, monkeypatch, score, protected_hit
):
    logits = np.full((1, 1, 240, 320), -1, np.float32)
    logits[:, :, 84:173, 208:272] = 1
    if protected_hit:
        logits[:, :, 108:150, 60:100] = 1
    encoder = SimpleNamespace(run=lambda *args: [np.zeros((1, 1), np.float32)] * 3)
    decoder = SimpleNamespace(run=lambda *args: (logits, np.array([[score]], dtype=np.float32)))
    monkeypatch.setattr(segmentation, "_sessions", lambda: (encoder, decoder))
    model_hash = segmentation.model_info()["sha256"]
    polygon = np.array(
        [
            [208, 84],
            [240, 84],
            [272, 84],
            [272, 129],
            [272, 173],
            [240, 173],
            [208, 173],
            [208, 129],
        ],
        dtype=np.float32,
    )
    with pytest.raises(ValueError, match="Your reel is unchanged"):
        segmentation.predict_mask(
            np.full((240, 320, 3), 100, np.uint8),
            polygon,
            np.array([[0.75, 0.54]], np.float32),
            np.array([[0.25, 0.54]], np.float32),
            (logits[0, 0] > 0).astype(np.uint8) * 255,
            model_hash,
        )


def test_mask_refinement_fills_small_clothing_holes_without_crossing_the_target():
    mask = np.zeros((240, 320), bool)
    mask[84:173, 208:272] = True
    mask[105:115, 230:238] = False
    refined = segmentation.refine_mask(mask, np.array([[0.25, 0.54]], np.float32))
    assert refined[110, 234] == 255
    assert refined[125, 220] == 255
    assert refined[120, 80] == 0
    assert refined[129, 80] == 0


@pytest.mark.parametrize("scale", [1, 3])
def test_mask_propagation_follows_local_motion_in_the_correct_direction_and_scale(scale):
    random = np.random.default_rng(42)
    texture = random.integers(30, 230, (80, 70), dtype=np.uint8)
    previous = np.full((240, 320), 30, np.uint8)
    current = previous.copy()
    previous[50:130, 40:110] = texture
    current[56:136, 52:122] = texture
    previous[80:160, 210:280] = texture
    current[80:160, 202:272] = texture
    mask = np.zeros_like(previous)
    mask[50:130, 40:110] = 255
    expected = np.zeros_like(mask)
    expected[56:136, 52:122] = 255
    arrays = [
        cv2.resize(array, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
        for array in (mask, previous, current, expected)
    ]
    moved = segmentation.propagate_mask(*arrays[:3]) > 0
    expected = arrays[3] > 0
    overlap = np.count_nonzero(moved & expected) / np.count_nonzero(moved | expected)
    assert overlap > 0.9
    assert not moved[:, 190 * scale :].any()


def test_tracking_refinement_only_adds_nearby_pixels_of_already_supported_components():
    guide = np.zeros((240, 320), np.uint8)
    guide[50:130, 40:112] = 255
    guide[50:130, 180:250] = 255
    mask = np.zeros_like(guide)
    mask[50:130, 40:110] = 255
    mask[50:130, 180:210] = 255
    guide[75, 100] = mask[75, 100] = 0
    refined = segmentation.refine_tracked_mask(mask, guide)
    assert refined[75, 111] == 255
    assert refined[75, 211] == 0
    assert refined[75, 100] == 0
    assert refined[160, 160] == 0
