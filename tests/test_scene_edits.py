import base64
import io
import json
import shutil
import threading
import time
import zipfile
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import httpx
import imageio_ffmpeg
import numpy as np
import pytest
from fastapi.testclient import TestClient
from openai import RateLimitError
from PIL import Image, ImageDraw

import server.director as director_module
import server.main as main_module
import server.visual as visual_module
from server.audio import SAMPLE_RATE, render_layers, wav_bytes
from server.config import Settings
from server.demo import DEMO_ASSETS, STYLE_FILENAME
from server.director import Director
from server.media import run_ffmpeg
from server.models import (
    CaptionAction,
    ColorRegion,
    ColorSelection,
    Media,
    MusicAction,
    Operation,
    Point,
    Project,
    RecolorAction,
    RecolorEffect,
    SceneDirection,
    SoundAction,
    SoundPassAction,
)
from server.visual import RecolorTrack


def selection(source_color="#c0232d", grounded=False, surface_kind="fabric"):
    points = [
        Point(x=x, y=y)
        for x, y in (
            (0.65, 0.35),
            (0.75, 0.35),
            (0.85, 0.35),
            (0.85, 0.54),
            (0.85, 0.72),
            (0.75, 0.72),
            (0.65, 0.72),
            (0.65, 0.54),
        )
    ]
    return ColorSelection(
        confidence=0.99,
        source_color=source_color,
        surface_kind=surface_kind,
        keyframes=[
            ColorRegion(
                time=time,
                points=[point.model_copy() for point in points],
                seeds=[Point(x=0.75, y=0.54)] if grounded else [],
                protected=[Point(x=0.25, y=0.54)] if grounded else [],
            )
            for time in (0, 0.5, 1, 1.5, 2)
        ],
    )


class SceneDirector:
    configured = True

    def __init__(self):
        self.direction = SceneDirection(message="What color would you like?")
        self.selection = selection(grounded=True)
        self.requests = []

    def scene_direction(self, project, path, request):
        self.requests.append(request)
        return self.direction

    def locate_color_target(self, project, path, target):
        return self.selection

    def analyze(self, project, path, brief):
        return project.model_copy(deep=True)


@pytest.fixture
def editing_client(tmp_path, monkeypatch):
    monkeypatch.setattr("server.main.mask_model_info", lambda: None)
    director = SceneDirector()
    app = main_module.create_app(
        Settings(
            data_dir=tmp_path / "app",
            storage_account="",
            openai_endpoint="",
            workspace_secret="scene-tests",
        ),
        director=director,
    )
    with TestClient(app) as client:
        yield client, director


@pytest.fixture
def blocked_direction(editing_client, monkeypatch):
    _, director = editing_client
    original = director.scene_direction
    entered, release = threading.Event(), threading.Event()

    def blocked(*args):
        entered.set()
        if not release.wait(5):
            raise RuntimeError("The test did not release its processing gate.")
        return original(*args)

    monkeypatch.setattr(director, "scene_direction", blocked)
    try:
        yield entered, release
    finally:
        release.set()


def finished_job(client, url):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(url)
        assert response.status_code == 200, response.text
        job = response.json()
        if job["status"] != "processing":
            return job
        time.sleep(0.01)
    pytest.fail("The accepted edit did not finish.")


@pytest.fixture
def people_video(tmp_path):
    image = Image.new("RGB", (320, 240), (38, 48, 42))
    draw = ImageDraw.Draw(image)
    for x in (48, 208):
        draw.ellipse((x + 14, 33, x + 49, 73), fill=(192, 142, 102))
        draw.rectangle((x, 84, x + 64, 172), fill=(192, 35, 45))
        draw.line((x + 9, 100, x + 53, 105), fill=(210, 57, 65), width=3)
        draw.rectangle((x + 4, 173, x + 59, 231), fill=(30, 34, 41))
    silent = tmp_path / "people-silent.mp4"
    writer = imageio_ffmpeg.write_frames(
        str(silent),
        (320, 240),
        fps=24,
        codec="libx264",
        macro_block_size=1,
        ffmpeg_log_level="error",
        output_params=["-crf", "18", "-threads", "1"],
    )
    writer.send(None)
    for _ in range(48):
        writer.send(image.tobytes())
    writer.close()
    time = np.arange(2 * SAMPLE_RATE) / SAMPLE_RATE
    audio = tmp_path / "original.wav"
    audio.write_bytes(
        wav_bytes(
            np.stack(
                [
                    0.08 * np.sin(2 * np.pi * 330 * time),
                    0.08 * np.sin(2 * np.pi * 440 * time),
                ],
                axis=1,
            )
        )
    )
    target = tmp_path / "people.mp4"
    run_ffmpeg(
        [
            "-i",
            str(silent),
            "-i",
            str(audio),
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(target),
        ]
    )
    return target


def upload(client, path):
    response = client.post(
        "/api/projects", files={"file": (path.name, path.read_bytes(), "video/mp4")}
    )
    assert response.status_code == 201, response.text
    return response.json()


def first_frame(path):
    frames = imageio_ffmpeg.read_frames(str(path), pix_fmt="rgb24")
    try:
        metadata = next(frames)
        width, height = metadata["size"]
        return np.frombuffer(next(frames), dtype=np.uint8).reshape(height, width, 3).copy()
    finally:
        frames.close()


def test_meta_mask_constrains_the_render_without_inference_on_every_frame(
    monkeypatch, people_video
):
    frame = first_frame(people_video)
    outline = selection(grounded=True)
    outline.keyframes = [outline.keyframes[0], outline.keyframes[-1]]
    for key in outline.keyframes:
        key.seeds = [Point(x=0.7, y=0.54)]
    learned = np.zeros(frame.shape[:2], np.uint8)
    learned[84:173, 208:240] = 255
    predictor = Mock(return_value=learned)
    monkeypatch.setattr("server.visual.predict_mask", predictor)
    monkeypatch.setattr(cv2, "calcOpticalFlowPyrLK", lambda *args, **kwargs: (None, None, None))
    effect = RecolorEffect(
        **outline.model_dump(),
        target="right shirt",
        color="#2872dd",
        mask_model="sam2.1-hiera-tiny",
        mask_model_sha256="a" * 64,
    )
    track = RecolorTrack(effect)
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    for timestamp in (0, 0.1, 0.2):
        changed = track.apply(frame, gray, timestamp)
        assert int(changed[125, 220, 2]) > int(changed[125, 220, 0]) + 60
        assert np.array_equal(changed[125, 260], frame[125, 260])
        assert np.array_equal(changed[:, :195], frame[:, :195])
    assert predictor.call_count == 1
    track.apply(frame, gray, 1.1)
    assert predictor.call_count == 2


@pytest.mark.parametrize("surface_kind", ["fabric", "object"])
def test_meta_fabric_disocclusion_recovers_color_but_object_holes_stay_excluded(
    monkeypatch, people_video, surface_kind
):
    revealed = first_frame(people_video)
    occluded = revealed.copy()
    occluded[112:140, 240:273] = (192, 142, 102)
    learned = np.zeros(revealed.shape[:2], np.uint8)
    learned[84:173, 208:273] = 255
    learned[112:140, 240:273] = 0
    predictor = Mock(return_value=learned)

    def propagate(mask, *args):
        moved = mask.copy()
        moved[112:140, 240:273] = 0
        return moved

    monkeypatch.setattr(visual_module, "predict_mask", predictor)
    monkeypatch.setattr(visual_module, "propagate_mask", propagate)
    monkeypatch.setattr(cv2, "calcOpticalFlowPyrLK", lambda *args, **kwargs: (None, None, None))
    outline = selection(grounded=True, surface_kind=surface_kind)
    for key in outline.keyframes:
        key.protected.append(Point(x=0.78, y=0.51))
    track = RecolorTrack(
        RecolorEffect(
            **outline.model_dump(),
            target="right surface",
            color="#2872dd",
            mask_model="sam2.1-hiera-tiny",
            mask_model_sha256="a" * 64,
        )
    )
    first = track.apply(occluded, cv2.cvtColor(occluded, cv2.COLOR_RGB2GRAY), 0)
    assert np.array_equal(first[125, 260], occluded[125, 260])
    changed = track.apply(revealed, cv2.cvtColor(revealed, cv2.COLOR_RGB2GRAY), 0.1)
    if surface_kind == "fabric":
        assert int(changed[125, 260, 2]) > int(changed[125, 260, 0]) + 60
    else:
        assert np.array_equal(changed[125, 260], revealed[125, 260])
    assert np.array_equal(changed[122, 249], revealed[122, 249])
    assert np.array_equal(changed[:, :195], revealed[:, :195])
    assert predictor.call_count == 1


def test_meta_render_samples_original_pixels_before_other_edits(
    monkeypatch, people_video, tmp_path
):
    folder = tmp_path / "meta-render"
    folder.mkdir()
    shutil.copyfile(people_video, folder / "source.mp4")
    right = selection(grounded=True)
    left = right.model_copy(deep=True)
    for key in left.keyframes:
        for point in key.points + key.seeds:
            point.x -= 0.5
        key.protected = [Point(x=0.75, y=0.54)]
    effects = [
        RecolorEffect(
            **outline.model_dump(),
            target=target,
            color=color,
            mask_model="sam2.1-hiera-tiny",
            mask_model_sha256="a" * 64,
        )
        for outline, target, color in (
            (right, "right shirt", "#2872dd"),
            (left, "left shirt", "#287d42"),
        )
    ]
    inputs = []

    def predictor(frame, polygon, seeds, protected, guide, model_sha256):
        inputs.append(frame.copy())
        return guide.copy()

    monkeypatch.setattr("server.visual.predict_mask", predictor)
    project = Project(
        media=Media(duration=2, fps=24, width=320, height=240, filename="people.mp4"),
        visual_edits=effects,
    )
    result = visual_module.prepare_preview(project, folder)
    assert result.is_file() and len(inputs) >= 2 and len(inputs) % 2 == 0
    for index in range(0, len(inputs), 2):
        assert np.array_equal(inputs[index], inputs[index + 1])
    assert np.array_equal(inputs[0], first_frame(people_video))


@pytest.mark.parametrize(
    ("meta", "elapsed", "succeeds"),
    [(True, 240, True), (True, 320, False), (False, 150, False)],
)
def test_meta_cpu_budget_allows_measured_work_but_remains_bounded(
    monkeypatch, people_video, tmp_path, meta, elapsed, succeeds
):
    folder = tmp_path / "budget"
    folder.mkdir()
    shutil.copyfile(people_video, folder / "source.mp4")
    effect = RecolorEffect(
        **selection(grounded=True).model_dump(),
        target="right shirt",
        color="#2872dd",
        mask_model="sam2.1-hiera-tiny" if meta else "opencv",
        mask_model_sha256="a" * 64 if meta else None,
    )
    project = Project(
        media=Media(duration=2, fps=24, width=320, height=240, filename="people.mp4"),
        visual_edits=[effect],
    )
    clock = [0.0]
    apply = RecolorTrack.apply

    def timed_apply(*args, **kwargs):
        result = apply(*args, **kwargs)
        clock[0] += elapsed / 48
        return result

    monkeypatch.setattr(visual_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(RecolorTrack, "apply", timed_apply)
    monkeypatch.setattr(visual_module, "predict_mask", lambda *args: args[4].copy())
    if succeeds:
        assert visual_module.prepare_preview(project, folder).is_file()
        assert clock[0] == elapsed and project.preview_id is not None
    else:
        with pytest.raises(ValueError, match="took too long"):
            visual_module.prepare_preview(project, folder)
        assert project.preview_id is None and not list((folder / "previews").glob("*.mp4"))


def test_meta_provider_is_saved_only_after_a_successful_render(
    editing_client, people_video, monkeypatch
):
    client, director = editing_client
    scene = upload(client, people_video)
    root = f"/api/projects/{scene['id']}"
    monkeypatch.setattr(
        "server.main.mask_model_info",
        lambda: {"name": "sam2.1-hiera-tiny", "sha256": "a" * 64},
    )
    director.direction = SceneDirection(
        message="The right shirt is blue.",
        actions=[RecolorAction(type="recolor", target="right shirt", color="#2872dd")],
    )
    predictor = Mock(side_effect=ValueError("Meta could not protect this surface."))
    monkeypatch.setattr("server.visual.predict_mask", predictor)
    request = {"revision": 0, "instruction": "Make the right shirt blue"}
    rejected = client.post(f"{root}/direct", json=request)
    assert rejected.status_code == 422
    untouched = client.get(root).json()
    assert untouched["revision"] == 0 and untouched["visual_edits"] == []

    predictor.side_effect = lambda frame, polygon, seeds, protected, guide, model_sha256: (
        guide.copy()
    )
    accepted = client.post(f"{root}/direct", json=request)
    assert accepted.status_code == 200, accepted.text
    changed = accepted.json()["project"]
    assert changed["revision"] == 1
    assert changed["visual_edits"][0]["mask_model"] == "sam2.1-hiera-tiny"
    assert changed["visual_edits"][0]["mask_model_sha256"] == "a" * 64
    assert predictor.call_count > 1


def test_off_white_clothing_recolors_across_lighting_without_changing_the_other_person():
    frame = np.full((240, 320, 3), (38, 48, 42), dtype=np.uint8)
    shades = np.linspace(253, 190, 89).astype(np.uint8)
    for x in (48, 208):
        frame[84:173, x : x + 64] = shades[:, None, None]
        frame[84:173, x : x + 64, 2] += 2
    outline = selection("#f5f3ee")
    for key in outline.keyframes:
        for point in key.points:
            point.x -= 0.05
            point.y -= 0.1
    track = RecolorTrack(
        RecolorEffect(**outline.model_dump(), target="right white shirt", color="#2872dd")
    )
    changed = track.apply(frame, cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY), 0)
    assert int(changed[86, 240, 2]) > int(changed[86, 240, 0]) + 60
    assert int(changed[125, 240, 2]) > int(changed[125, 240, 0]) + 60
    assert int(changed[125, 212, 2]) > int(changed[125, 212, 0]) + 60
    assert int(changed[165, 240, 2]) > int(changed[165, 240, 0]) + 60
    assert np.array_equal(changed[:, :195], frame[:, :195])
    assert changed[105, 240].mean() > changed[150, 240].mean() + 15


def test_touching_same_color_saucer_is_not_recolored_with_the_cup():
    frame = np.full((240, 320, 3), (38, 48, 42), dtype=np.uint8)
    white = (225, 230, 235)
    cv2.rectangle(frame, (208, 84), (272, 172), white, -1)
    cv2.ellipse(frame, (240, 190), (65, 13), 0, 0, 360, white, -1)
    cv2.rectangle(frame, (235, 169), (245, 180), white, -1)
    outline = selection("#f5f3ee", grounded=True, surface_kind="object")
    for key in outline.keyframes:
        key.protected = [Point(x=0.75, y=0.8)]
    effect = RecolorEffect(**outline.model_dump(), target="cup body", color="#2872dd")
    changed = RecolorTrack(effect).apply(frame, cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY), 0)
    assert int(changed[125, 240, 2]) > int(changed[125, 240, 0]) + 60
    assert np.array_equal(changed[185:210], frame[185:210])


def test_fabric_folds_do_not_split_one_shirt_into_partial_color_patches():
    frame = np.full((240, 320, 3), (38, 48, 42), dtype=np.uint8)
    for x in (48, 208):
        frame[84:173, x : x + 64] = (242, 245, 248)
        frame[123:127, x : x + 64] = (198, 204, 208)
    effect = RecolorEffect(
        **selection("#f5f3ee", grounded=True).model_dump(),
        target="right shirt",
        color="#2872dd",
    )
    changed = RecolorTrack(effect).apply(frame, cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY), 0)
    assert int(changed[100, 240, 2]) > int(changed[100, 240, 0]) + 60
    assert int(changed[150, 240, 2]) > int(changed[150, 240, 0]) + 60
    assert np.array_equal(changed[:, :195], frame[:, :195])


def test_subtle_contact_edge_separates_a_white_cup_from_its_white_saucer():
    frame = np.full((240, 320, 3), (38, 48, 42), dtype=np.uint8)
    cv2.rectangle(frame, (208, 84), (272, 172), (225, 225, 225), -1)
    cv2.rectangle(frame, (180, 172), (300, 194), (225, 225, 225), -1)
    cv2.line(frame, (208, 172), (272, 172), (222, 222, 222), 1)
    outline = selection("#f5f3ee", grounded=True, surface_kind="object")
    for key in outline.keyframes:
        key.points = [
            Point(x=x, y=y)
            for x, y in (
                (0.55, 0.33),
                (0.75, 0.33),
                (0.98, 0.33),
                (0.98, 0.59),
                (0.98, 0.85),
                (0.75, 0.85),
                (0.55, 0.85),
                (0.55, 0.59),
            )
        ]
        key.protected = [Point(x=0.75, y=0.79)]
    effect = RecolorEffect(**outline.model_dump(), target="cup body", color="#2872dd")
    changed = RecolorTrack(effect).apply(frame, cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY), 0)
    assert int(changed[125, 240, 2]) > int(changed[125, 240, 0]) + 60
    assert np.array_equal(changed[185:195], frame[185:195])


def test_small_target_is_not_crowded_out_by_large_background_regions():
    image = Image.new("RGB", (400, 320), (38, 48, 42))
    draw = ImageDraw.Draw(image)
    for x in range(10, 390, 38):
        for y in range(10, 310, 38):
            if abs(x + 12 - 200) < 38 and abs(y + 12 - 160) < 38:
                continue
            draw.rectangle((x, y, x + 24, y + 24), fill=(192, 35, 45))
    draw.rectangle((192, 152, 208, 168), fill=(192, 35, 45))
    region = selection().keyframes[0].model_copy(deep=True)
    for point in region.points:
        point.x -= 0.25
        point.y -= 0.04
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    _, candidates, _ = director_module.surface_reference(
        base64.b64encode(buffer.getvalue()).decode(), "#c0232d", region, "fabric"
    )
    assert any(
        192 <= candidate["point"].x * 399 <= 208 and 152 <= candidate["point"].y * 319 <= 168
        for candidate in candidates
    )


def test_pale_face_is_not_proposed_as_a_saturated_painted_body():
    image = Image.new("RGB", (320, 240), (38, 48, 42))
    draw = ImageDraw.Draw(image)
    draw.rectangle((208, 84, 272, 172), fill=(217, 138, 90))
    draw.ellipse((216, 32, 264, 72), fill=(242, 226, 207))
    region = selection().keyframes[0].model_copy(deep=True)
    for point in region.points:
        point.y -= 0.3
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    _, candidates, _ = director_module.surface_reference(
        base64.b64encode(buffer.getvalue()).decode(), "#d98a5a", region, "object"
    )
    assert candidates
    assert all(
        not (216 <= candidate["point"].x * 319 <= 264 and 32 <= candidate["point"].y * 239 <= 72)
        for candidate in candidates
    )
    assert any(
        208 <= candidate["point"].x * 319 <= 272 and 84 <= candidate["point"].y * 239 <= 172
        for candidate in candidates
    )


def test_nearby_small_highlights_do_not_crop_away_the_main_target_surface():
    image = Image.new("RGB", (400, 320), (38, 48, 42))
    draw = ImageDraw.Draw(image)
    for box in ((105, 120, 155, 240), (193, 153, 205, 163), (193, 178, 205, 188)):
        draw.rectangle(box, fill=(192, 35, 45))
    region = ColorRegion(
        time=0,
        points=[
            Point(x=x, y=y)
            for x, y in (
                (0.38, 0.42),
                (0.5, 0.42),
                (0.62, 0.42),
                (0.62, 0.54),
                (0.62, 0.66),
                (0.5, 0.66),
                (0.38, 0.66),
                (0.38, 0.54),
            )
        ],
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    _, candidates, _ = director_module.surface_reference(
        base64.b64encode(buffer.getvalue()).decode(), "#c0232d", region, "object"
    )
    assert any(
        105 <= candidate["point"].x * 399 <= 155 and 120 <= candidate["point"].y * 319 <= 240
        for candidate in candidates
    )


def test_dark_blue_fabric_folds_remain_one_visible_garment_surface():
    image = Image.new("RGB", (320, 240), (38, 48, 42))
    draw = ImageDraw.Draw(image)
    draw.rectangle((208, 84, 272, 172), fill=(46, 54, 95))
    draw.rectangle((222, 84, 228, 172), fill=(14, 18, 30))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    _, candidates, _ = director_module.surface_reference(
        base64.b64encode(buffer.getvalue()).decode(),
        "#2e365f",
        selection().keyframes[0],
        "fabric",
    )
    assert len(candidates) == 1


@pytest.mark.parametrize("source_color", ["#2e365f", "#2f3a6f"])
def test_real_stock_clothing_is_not_fragmented_by_a_plausible_model_color(source_color):
    frame = first_frame(DEMO_ASSETS / STYLE_FILENAME)
    outline = ColorSelection(
        source_color=source_color,
        surface_kind="fabric",
        confidence=0.99,
        keyframes=[
            ColorRegion(
                time=time,
                points=[
                    Point(x=x, y=y)
                    for x, y in (
                        (0, 0.16),
                        (0.24, 0.16),
                        (0.48, 0.16),
                        (0.48, 0.58),
                        (0.48, 1),
                        (0.24, 1),
                        (0, 1),
                        (0, 0.58),
                    )
                ],
                seeds=[Point(x=0.22, y=0.22), Point(x=0.2, y=0.5), Point(x=0.12, y=0.9)],
                protected=[Point(x=0.75, y=0.45)],
            )
            for time in (0, 6)
        ],
    )
    effect = RecolorEffect(**outline.model_dump(), target="left outfit", color="#C66A4A")
    changed = RecolorTrack(effect).apply(frame, cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY), 0)
    hue = cv2.cvtColor(changed.astype(np.float32) / 255, cv2.COLOR_RGB2HLS)[:, :, 0]
    for top, bottom, left, right in ((380, 520, 70, 180), (850, 940, 35, 85), (205, 225, 100, 145)):
        cloth = frame[top:bottom, left:right].astype(int)
        visibly_blue = (cloth[:, :, 2] > cloth[:, :, 0] + 15) & (
            cloth[:, :, 2] > cloth[:, :, 1] + 10
        )
        assert visibly_blue.sum() > 300
        converted = np.abs(hue[top:bottom, left:right] - 15.5) < 12
        assert converted[visibly_blue].mean() > 0.95
    assert np.array_equal(changed[255:315, 90:170], frame[255:315, 90:170])
    assert np.array_equal(changed[:, 330:], frame[:, 330:])


@pytest.mark.parametrize("scale", [1, 3])
def test_clothing_at_the_frame_edge_is_recolored_without_touching_the_other_person(scale):
    frame = np.full((240, 320, 3), (38, 48, 42), dtype=np.uint8)
    frame[80:220, :128] = (46, 54, 95)
    frame[80:220, 220:280] = (46, 54, 95)
    frame = cv2.resize(frame, (320 * scale, 240 * scale), interpolation=cv2.INTER_NEAREST)
    outline = ColorSelection(
        source_color="#2e365f",
        surface_kind="fabric",
        confidence=0.99,
        keyframes=[
            ColorRegion(
                time=time,
                points=[
                    Point(x=x, y=y)
                    for x, y in (
                        (0, 0.3),
                        (0.2, 0.3),
                        (0.4, 0.3),
                        (0.4, 0.6),
                        (0.4, 0.85),
                        (0.2, 0.85),
                        (0, 0.85),
                        (0, 0.6),
                    )
                ],
                seeds=[Point(x=0.15, y=0.6)],
                protected=[Point(x=0.75, y=0.6)],
            )
            for time in (0, 2)
        ],
    )
    effect = RecolorEffect(**outline.model_dump(), target="left outfit", color="#C66A4A")
    changed = RecolorTrack(effect).apply(frame, cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY), 0)
    assert int(changed[140 * scale, 0, 0]) > int(changed[140 * scale, 0, 2]) + 60
    boundary_hue = cv2.cvtColor(
        changed[140 * scale : 140 * scale + 1, 128 * scale - 1 : 128 * scale].astype(np.float32)
        / 255,
        cv2.COLOR_RGB2HLS,
    )[0, 0, 0]
    assert abs(float(boundary_hue) - 15.5) < 2
    assert int(changed[215 * scale, 50 * scale, 0]) > int(changed[215 * scale, 50 * scale, 2]) + 60
    assert np.array_equal(changed[:, 200 * scale :], frame[:, 200 * scale :])
    assert np.array_equal(changed[: 70 * scale], frame[: 70 * scale])


@pytest.mark.parametrize(
    ("ids", "confidence", "accepted"),
    (([1], 0.95, True), ([999], 0.95, False), ([1], 0.4, False), ([], 0.95, False)),
)
def test_director_grounds_coarse_coordinates_in_valid_image_regions(
    tmp_path, monkeypatch, ids, confidence, accepted
):
    image = Image.new("RGB", (320, 240), (38, 48, 42))
    draw = ImageDraw.Draw(image)
    for x in (48, 208):
        draw.rectangle((x, 84, x + 64, 172), fill=(192, 35, 45))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    outline = selection()
    for key in outline.keyframes:
        for point in key.points:
            point.x -= 0.05
            point.y -= 0.1
    frames = [
        {"time": key.time, "image": base64.b64encode(buffer.getvalue()).decode()}
        for key in outline.keyframes
    ]
    monkeypatch.setattr("server.director.analysis_frames", lambda *args, **kwargs: frames)
    director = Director(Settings(data_dir=tmp_path, openai_endpoint="https://example.invalid"))
    client = Mock()
    client.with_options.return_value = client
    rough = {
        "source_color": outline.source_color,
        "surface_kind": outline.surface_kind,
        "confidence": outline.confidence,
        "frames": {
            f"frame_{index}": {
                "visible": True,
                "x": sum(point.x for point in key.points) / 8,
                "y": sum(point.y for point in key.points) / 8,
            }
            for index, key in enumerate(outline.keyframes)
        },
    }
    client.chat.completions.create.side_effect = [
        SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(rough)))]
        ),
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        tool_calls=[
                            SimpleNamespace(
                                function=SimpleNamespace(
                                    name="choose_surfaces",
                                    arguments=json.dumps(
                                        {
                                            "confidence": confidence,
                                            "frames": {
                                                f"frame_{index}": ids
                                                for index in range(len(frames))
                                            },
                                        }
                                    ),
                                )
                            )
                        ]
                    )
                )
            ]
        ),
    ]
    director._client = client
    project = Project(
        name="Two shirts",
        media=Media(duration=2, fps=24, width=320, height=240, filename="people.mp4"),
    )
    if not accepted:
        with pytest.raises(ValueError):
            director.locate_color_target(project, tmp_path / "source.mp4", "right shirt")
        return
    grounded = director.locate_color_target(project, tmp_path / "source.mp4", "right shirt")
    effect = RecolorEffect(**grounded.model_dump(), target="right shirt", color="#2872dd")
    frame = np.array(image)
    changed = RecolorTrack(effect).apply(frame, cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY), 0)
    assert int(changed[125, 240, 2]) > int(changed[125, 240, 0]) + 60
    assert int(changed[165, 240, 2]) > int(changed[165, 240, 0]) + 60
    assert np.array_equal(changed[:, :195], frame[:, :195])


def test_combined_recolor_music_changes_only_the_right_shirt_and_undoes_atomically(
    editing_client, people_video, tmp_path
):
    client, director = editing_client
    scene = upload(client, people_video)
    assert scene["media"]["has_audio"]
    original_video = client.get(f"/api/projects/{scene['id']}/source.mp4").content
    original_audio = client.get(f"/api/projects/{scene['id']}/original.wav").content
    director.direction = SceneDirection(
        message="The shirt on the right is blue.",
        actions=[
            CaptionAction(type="caption", text="A NEW MOOD"),
            RecolorAction(
                type="recolor", target="the shirt of the guy on the right", color="#2872dd"
            ),
            MusicAction(type="music"),
        ],
    )
    response = client.post(
        f"/api/projects/{scene['id']}/direct",
        json={
            "revision": 0,
            "instruction": "Make the guy on the right's shirt blue.",
        },
    )
    assert response.status_code == 200, response.text
    changed = response.json()["project"]
    assert changed["preview_id"] and changed["revision"] == 1
    assert changed["music"]["style"] == "ambient"
    assert changed["caption"]["text"] == "A NEW MOOD"
    assert changed["objects"] == scene["objects"] and changed["cues"] == scene["cues"]
    assert not changed["source_audio_muted"]
    assert client.get(f"/api/projects/{scene['id']}/source.mp4").content == original_video
    assert client.get(f"/api/projects/{scene['id']}/original.wav").content == original_audio
    preview_url = f"/api/projects/{scene['id']}/previews/{changed['preview_id']}.mp4"
    preview = client.get(preview_url)
    assert preview.status_code == 200
    preview_path = tmp_path / "preview.mp4"
    preview_path.write_bytes(preview.content)
    frame = first_frame(preview_path)
    assert int(frame[125, 240, 2]) > int(frame[125, 240, 0]) + 60
    assert int(frame[125, 80, 0]) > int(frame[125, 80, 2]) + 100
    assert int(frame[50, 240, 0]) > int(frame[50, 240, 2]) + 40
    with TestClient(client.app) as stranger:
        assert stranger.get(preview_url).status_code == 404

    exported = client.post(f"/api/projects/{scene['id']}/exports", json={"revision": 1})
    assert exported.status_code == 200, exported.text
    movie = tmp_path / "finished.mp4"
    movie.write_bytes(client.get(exported.json()["video_url"]).content)
    assert np.array_equal(first_frame(movie), frame)
    bundle = client.get(exported.json()["bundle_url"]).content
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        assert archive.read("source.mp4") == original_video
        assert archive.read("source-audio.wav") == original_audio
        assert "layers/original-audio.wav" in archive.namelist()
    restored = client.post(
        "/api/projects/import", files={"file": ("reel.zip", bundle, "application/zip")}
    )
    assert restored.status_code == 201, restored.text
    imported = restored.json()
    assert imported["visual_edits"] == changed["visual_edits"]
    assert imported["caption"] == changed["caption"]
    imported_preview = client.get(
        f"/api/projects/{imported['id']}/previews/{imported['preview_id']}.mp4"
    )
    assert imported_preview.status_code == 200
    imported_path = tmp_path / "imported-preview.mp4"
    imported_path.write_bytes(imported_preview.content)
    assert np.array_equal(first_frame(imported_path), frame)
    undone = client.post(f"/api/projects/{scene['id']}/undo", json={"revision": 1}).json()
    assert not undone["visual_edits"] and undone["preview_id"] is None
    assert undone["music"] is None
    assert undone["caption"] is None
    assert client.get(f"/api/projects/{scene['id']}/original.wav").content == original_audio


def test_ambient_music_changes_the_mix_without_touching_foley_and_can_be_undone(editing_client):
    client, director = editing_client
    scene = client.post("/api/demo").json()
    library = client.app.state.studio.library
    baseline = render_layers(Project.model_validate(scene), library)
    director.direction = SceneDirection(
        message="Ambient music is on.", actions=[MusicAction(type="music")]
    )
    response = client.post(
        f"/api/projects/{scene['id']}/direct",
        json={"revision": 0, "instruction": "Add ambient music"},
    )
    assert response.status_code == 200, response.text
    changed = response.json()["project"]
    assert changed["cues"] == scene["cues"] and changed["objects"] == scene["objects"]
    layers = render_layers(Project.model_validate(changed), library)
    for key in baseline:
        assert np.array_equal(baseline[key], layers[key])
    assert layers[""].shape == (8 * SAMPLE_RATE, 2)
    assert np.sqrt(np.mean(layers[""] ** 2)) > 0.015
    assert not np.array_equal(layers[""][:, 0], layers[""][:, 1])
    assert client.get(f"/api/projects/{scene['id']}/music.wav").status_code == 200
    result = client.post(f"/api/projects/{scene['id']}/exports", json={"revision": 1}).json()
    bundle = client.get(result["bundle_url"]).content
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        assert "layers/ambient-music.wav" in archive.namelist()
    imported = client.post(
        "/api/projects/import", files={"file": ("reel.zip", bundle, "application/zip")}
    ).json()
    assert imported["music"] == changed["music"]
    undone = client.post(f"/api/projects/{scene['id']}/undo", json={"revision": 1}).json()
    assert undone["music"] is None
    assert client.get(f"/api/projects/{scene['id']}/music.wav").status_code == 404


def test_color_grounding_uses_physical_source_pixels_not_a_rendered_title(
    editing_client, people_video, tmp_path
):
    client, director = editing_client
    scene = upload(client, people_video)
    root = f"/api/projects/{scene['id']}"
    source = tmp_path / "source-copy.mp4"
    source.write_bytes(client.get(f"{root}/source.mp4").content)
    director.direction = SceneDirection(
        message="Added a title.", actions=[CaptionAction(type="caption", text="MY REEL")]
    )
    response = client.post(
        f"{root}/direct", json={"revision": 0, "instruction": "Add the title 'MY REEL'"}
    )
    assert response.status_code == 200
    assert response.json()["project"]["preview_id"]
    director.locate_color_target = Mock(wraps=director.locate_color_target)
    director.direction = SceneDirection(
        message="Recolored the right shirt.",
        actions=[RecolorAction(type="recolor", target="right shirt", color="#2872dd")],
    )
    response = client.post(
        f"{root}/direct", json={"revision": 1, "instruction": "Make the right shirt blue"}
    )
    assert response.status_code == 200, response.text
    inspected_path = director.locate_color_target.call_args.args[1]
    assert np.array_equal(first_frame(inspected_path), first_frame(source))
    assert response.json()["project"]["caption"]["text"] == "MY REEL"


def test_removing_a_nonexistent_title_does_not_claim_to_erase_source_text(
    editing_client, people_video
):
    client, director = editing_client
    before = upload(client, people_video)
    director.direction = SceneDirection(
        message="Removed the title and added music.",
        actions=[
            MusicAction(type="music", gain_db=-12),
            CaptionAction(type="caption", text=None),
        ],
    )
    response = client.post(
        f"/api/projects/{before['id']}/direct",
        json={"revision": 0, "instruction": "Remove the embedded title and add ambient music"},
    )
    assert 400 <= response.status_code < 500
    assert "no editable title" in response.text.lower()
    assert client.get(f"/api/projects/{before['id']}").json() == before


@pytest.mark.parametrize("title", ["A NEW MOOD", "W" * 80])
def test_title_only_edit_changes_video_pixels_and_can_be_removed(
    editing_client, people_video, tmp_path, title
):
    client, director = editing_client
    scene = upload(client, people_video)
    source = client.get(f"/api/projects/{scene['id']}/source.mp4").content
    director.direction = SceneDirection(
        message="Added your title.",
        actions=[CaptionAction(type="caption", text=title)],
    )
    response = client.post(
        f"/api/projects/{scene['id']}/direct",
        json={"revision": 0, "instruction": f"Add the title '{title}'"},
    )
    assert response.status_code == 200, response.text
    changed = response.json()["project"]
    assert changed["preview_id"] and changed["caption"]["text"] == title
    path = tmp_path / "titled.mp4"
    path.write_bytes(
        client.get(f"/api/projects/{scene['id']}/previews/{changed['preview_id']}.mp4").content
    )
    baseline = tmp_path / "normalized-source.mp4"
    baseline.write_bytes(source)
    before, after = first_frame(baseline), first_frame(path)
    difference = np.max(np.abs(after.astype(int) - before.astype(int)), axis=2)
    assert np.count_nonzero(difference[170:225] > 40) > 200
    assert np.mean(np.abs(after[:65].astype(int) - before[:65].astype(int))) < 3
    _, ink_x = np.where(np.all(after > (235, 230, 215), axis=2))
    assert len(ink_x) > 50
    assert ink_x.min() >= before.shape[1] * 0.05
    assert ink_x.max() <= before.shape[1] * 0.95
    assert client.get(f"/api/projects/{scene['id']}/source.mp4").content == source
    director.direction = SceneDirection(
        message="Removed your title.", actions=[CaptionAction(type="caption", text=None)]
    )
    removed = client.post(
        f"/api/projects/{scene['id']}/direct",
        json={"revision": 1, "instruction": "Remove the title"},
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["project"]["caption"] is None
    assert removed.json()["project"]["preview_id"] is None


def test_replacing_music_mutes_but_retains_original_soundtrack(editing_client, people_video):
    client, director = editing_client
    scene = upload(client, people_video)
    original = client.get(f"/api/projects/{scene['id']}/original.wav").content
    director.direction = SceneDirection(
        message="Replaced the original soundtrack with ambient music.",
        actions=[MusicAction(type="music", replace_original=True)],
    )
    response = client.post(
        f"/api/projects/{scene['id']}/direct",
        json={"revision": 0, "instruction": "Change the music to ambient"},
    )
    assert response.status_code == 200, response.text
    changed = Project.model_validate(response.json()["project"])
    assert changed.source_audio_muted and changed.music
    assert ":source" not in render_layers(changed, client.app.state.studio.library)
    assert client.get(f"/api/projects/{scene['id']}/original.wav").content == original
    restored = client.post(f"/api/projects/{scene['id']}/undo", json={"revision": 1}).json()
    assert not restored["source_audio_muted"] and restored["music"] is None


def test_scene_chat_infers_sound_scope_and_receives_history_without_manual_selection(
    editing_client,
):
    client, director = editing_client
    scene = client.post("/api/demo").json()
    director.direction = SceneDirection(
        message="The cup is quieter.",
        actions=[
            SoundAction(
                type="sound", object_id="cup", operations=[Operation(type="gain", value=-3)]
            )
        ],
    )
    history = [{"role": "user", "text": "Let's work on the cup."}]
    response = client.post(
        f"/api/projects/{scene['id']}/direct",
        json={"revision": 0, "instruction": "Make it quieter", "history": history},
    )
    assert response.status_code == 200, response.text
    changed = response.json()["project"]
    assert director.requests[-1].object_id is None
    assert director.requests[-1].history[0].text == history[0]["text"]
    assert [obj for obj in changed["objects"] if obj["id"] != "cup"] == [
        obj for obj in scene["objects"] if obj["id"] != "cup"
    ]
    assert next(obj for obj in changed["objects"] if obj["id"] == "cup")["gain_db"] == -3
    assert changed["cues"] == scene["cues"]
    rejected = client.post(
        f"/api/projects/{scene['id']}/direct",
        json={"revision": 1, "instruction": "Make this quieter", "object_id": "pour"},
    )
    assert rejected.status_code == 422
    assert client.get(f"/api/projects/{scene['id']}").json() == changed


def test_unresolved_or_unrenderable_edits_do_not_claim_success_or_change_the_scene(
    editing_client, people_video
):
    client, director = editing_client
    scene = upload(client, people_video)
    question = client.post(
        f"/api/projects/{scene['id']}/direct",
        json={"revision": 0, "instruction": "Change the shirt color"},
    )
    assert question.status_code == 200
    assert question.json()["project"]["revision"] == 0
    assert question.json()["message"] == "What color would you like?"
    director.direction = SceneDirection(
        message="Your sound pass is ready.",
        actions=[SoundPassAction(type="sound_pass", brief="A cinematic sound pass")],
    )
    empty_pass = client.post(
        f"/api/projects/{scene['id']}/direct",
        json={"revision": 0, "instruction": "Create a cinematic sound pass"},
    )
    assert empty_pass.status_code == 422 and "couldn't find" in empty_pass.json()["detail"]
    director.selection = selection("#00ff00")
    director.direction = SceneDirection(
        message="The shirt is blue.",
        actions=[
            MusicAction(type="music"),
            RecolorAction(type="recolor", target="right shirt", color="#2872dd"),
        ],
    )
    response = client.post(
        f"/api/projects/{scene['id']}/direct", json={"revision": 0, "instruction": "Blue"}
    )
    assert response.status_code == 422 and "couldn't isolate" in response.json()["detail"]
    current = client.get(f"/api/projects/{scene['id']}").json()
    assert (
        current["revision"] == 0 and not current["visual_edits"] and current["preview_id"] is None
    )
    assert current["music"] is None
    assert not list(
        (client.app.state.settings.data_dir / "media" / scene["id"]).rglob("*.partial.mp4")
    )


def test_model_capacity_errors_are_retryable_without_losing_the_scene(editing_client, monkeypatch):
    client, director = editing_client
    scene = client.post("/api/demo").json()

    def at_capacity(*args):
        raise RateLimitError(
            "At capacity",
            response=httpx.Response(
                429, request=httpx.Request("POST", "https://example.invalid/director")
            ),
            body={},
        )

    with monkeypatch.context() as patch:
        patch.setattr(director, "scene_direction", at_capacity)
        response = client.post(
            f"/api/projects/{scene['id']}/direct",
            json={"revision": 0, "instruction": "Make the cup blue"},
        )
    assert response.status_code == 429 and response.headers["retry-after"] == "60"
    assert "unchanged" in response.json()["detail"]
    assert client.get(f"/api/projects/{scene['id']}").json() == scene
    retried = client.post(
        f"/api/projects/{scene['id']}/direct",
        json={"revision": 0, "instruction": "Change the cup's color"},
    )
    assert retried.status_code == 200 and retried.json()["project"]["revision"] == 0


def test_async_edit_returns_before_work_finishes_and_is_private_and_exclusive(
    editing_client, blocked_direction
):
    client, director = editing_client
    scene = client.post("/api/demo").json()
    root = f"/api/projects/{scene['id']}"
    director.direction = SceneDirection(
        message="The cup is quieter.",
        actions=[
            SoundAction(
                type="sound", object_id="cup", operations=[Operation(type="gain", value=-3)]
            )
        ],
    )
    entered, release = blocked_direction
    body = {"revision": 0, "instruction": "Make the cup quieter"}
    accepted = client.post(f"{root}/direct", headers={"Prefer": "respond-async"}, json=body)
    assert accepted.status_code == 202, accepted.text
    assert "project" not in accepted.json()
    status_url = accepted.json()["status_url"]
    assert accepted.headers["location"] == status_url
    assert entered.wait(2)
    assert client.get(status_url).json()["status"] == "processing"
    assert client.get(root).json() == scene
    assert (
        client.post(f"{root}/direct", headers={"Prefer": "respond-async"}, json=body).status_code
        == 429
    )
    cookies = httpx.Cookies(client.cookies)
    try:
        client.cookies.clear()
        assert client.get(status_url).status_code == 404
    finally:
        client.cookies = cookies
        release.set()
    completed = finished_job(client, status_url)
    assert completed["status"] == "completed", completed
    changed = completed["result"]["project"]
    assert changed["revision"] == 1
    assert next(obj for obj in changed["objects"] if obj["id"] == "cup")["gain_db"] == -3
    assert changed["cues"] == scene["cues"]
    assert client.get(root).json() == changed
    renamed = client.patch(root, json={"revision": 1, "name": "A later edit"}).json()
    assert renamed["revision"] == 2
    assert client.get(status_url).json() == completed
    director.direction = SceneDirection(message="What next?")
    assert client.post(f"{root}/direct", json={**body, "revision": 2}).status_code == 200


@pytest.mark.parametrize(
    ("failure", "status"), [("render", 422), ("capacity", 429), ("unexpected", 503)]
)
def test_async_failures_preserve_the_scene_and_release_processing_capacity(
    editing_client, monkeypatch, failure, status
):
    client, director = editing_client
    scene = client.post("/api/demo").json()
    root = f"/api/projects/{scene['id']}"
    director.direction = SceneDirection(
        message="The cup is quieter.",
        actions=[
            SoundAction(
                type="sound", object_id="cup", operations=[Operation(type="gain", value=-3)]
            )
        ],
    )
    body = {"revision": 0, "instruction": "Make the cup quieter"}

    def fail(*args):
        if failure == "render":
            raise ValueError("This color edit took too long. Try a shorter clip.")
        if failure == "capacity":
            raise RateLimitError(
                "private-provider-details",
                response=httpx.Response(
                    429, request=httpx.Request("POST", "https://example.invalid/director")
                ),
                body={},
            )
        raise RuntimeError("private-provider-details")

    with monkeypatch.context() as patch:
        if failure == "render":
            patch.setattr(main_module, "prepare_preview", fail)
        else:
            patch.setattr(director, "scene_direction", fail)
        accepted = client.post(f"{root}/direct", headers={"Prefer": "respond-async"}, json=body)
        assert accepted.status_code == 202, accepted.text
        job = finished_job(client, accepted.json()["status_url"])
    assert job["status"] == "failed" and job["error_status"] == status
    assert "private-provider-details" not in json.dumps(job)
    assert client.get(root).json() == scene
    retried = client.post(f"{root}/direct", json=body)
    assert retried.status_code == 200, retried.text
    assert retried.json()["project"]["revision"] == 1


def test_async_completion_cannot_overwrite_a_newer_revision(editing_client, blocked_direction):
    client, director = editing_client
    scene = client.post("/api/demo").json()
    root = f"/api/projects/{scene['id']}"
    director.direction = SceneDirection(message="Music is on.", actions=[MusicAction(type="music")])
    entered, release = blocked_direction
    accepted = client.post(
        f"{root}/direct",
        headers={"Prefer": "respond-async"},
        json={"revision": 0, "instruction": "Add ambient music"},
    )
    assert accepted.status_code == 202
    assert entered.wait(2)
    try:
        renamed = client.patch(root, json={"revision": 0, "name": "Saved in another tab"})
        assert renamed.status_code == 200
    finally:
        release.set()
    job = finished_job(client, accepted.json()["status_url"])
    assert job["status"] == "failed" and job["error_status"] == 409
    assert client.get(root).json() == renamed.json()
    assert renamed.json()["music"] is None


def test_async_receipts_can_expire_without_losing_the_saved_reel(editing_client):
    client, director = editing_client
    scene = client.post("/api/demo").json()
    root = f"/api/projects/{scene['id']}"
    director.direction = SceneDirection(message="Music is on.", actions=[MusicAction(type="music")])
    accepted = client.post(
        f"{root}/direct",
        headers={"Prefer": "respond-async"},
        json={"revision": 0, "instruction": "Add ambient music"},
    )
    assert accepted.status_code == 202
    status_url = accepted.json()["status_url"]
    job = finished_job(client, status_url)
    assert job["status"] == "completed"
    restarted_app = main_module.create_app(client.app.state.settings, director=director)
    with TestClient(restarted_app) as restarted:
        restarted.cookies = client.cookies
        missing = restarted.get(status_url)
        assert missing.status_code == 404 and "Reload" in missing.json()["detail"]
        assert restarted.get(root).json() == job["result"]["project"]
        stale = restarted.post(
            f"{root}/direct",
            headers={"Prefer": "respond-async"},
            json={"revision": 0, "instruction": "Add ambient music"},
        )
        assert stale.status_code == 409
