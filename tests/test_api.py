import io
import json
import wave
import zipfile

import numpy as np
import pytest
from fastapi.testclient import TestClient

from server.audio import SAMPLE_RATE, wav_bytes
from server.demo import DEMO_ASSETS, STYLE_FILENAME
from server.media import analysis_frames, probe


def create_scene(client):
    result = client.post("/api/demo")
    assert result.status_code == 201, result.text
    return result.json()


def test_stock_demo_is_portrait_and_its_editable_sound_assets_are_available(client):
    scene = create_scene(client)
    assert scene["media"]["height"] > scene["media"]["width"]
    assert scene["cues"] and len(scene["objects"]) > 1
    for asset in scene["assets"]:
        response = client.get(f"/api/projects/{scene['id']}/assets/{asset['id']}.wav")
        assert response.status_code == 200
        with wave.open(io.BytesIO(response.content)) as audio:
            assert audio.getnframes() == round(asset["duration"] * SAMPLE_RATE)
            samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")
            assert np.max(np.abs(samples)) > 1000
    editable = {asset["id"] for asset in scene["assets"]}
    assert {cue["asset_id"] for cue in scene["cues"]} <= editable
    assert client.get(f"/api/projects/{scene['id']}/poster.jpg").status_code == 200


def test_browser_workspaces_are_isolated_and_source_supports_seeking(client):
    scene = create_scene(client)
    assert len(client.get("/api/projects").json()) == 1
    assert client.cookies["fg_workspace"]
    response = client.get(
        f"/api/projects/{scene['id']}/source.mp4", headers={"Range": "bytes=0-63"}
    )
    assert response.status_code == 206
    assert len(response.content) == 64
    with TestClient(client.app) as stranger:
        assert stranger.get("/api/projects").json() == []
        assert stranger.get(f"/api/projects/{scene['id']}").status_code == 404
        assert stranger.get(f"/api/projects/{scene['id']}/source.mp4").status_code == 404
    blocked = client.post(
        f"/api/projects/{scene['id']}/edit",
        headers={"Origin": "https://another-site.example"},
        json={"revision": 0, "object_id": "pour", "operations": [{"type": "gain", "value": 12}]},
    )
    assert blocked.status_code == 403
    assert client.get(f"/api/projects/{scene['id']}").json()["revision"] == 0


def test_people_demo_serves_the_real_stock_clip_and_rejects_unknown_scenes(client):
    response = client.post("/api/demo?scene=style")
    assert response.status_code == 201, response.text
    scene = response.json()
    assert scene["media"]["height"] > scene["media"]["width"]
    assert "pexels.com/video/" in scene["source_credit"]
    assert not scene["objects"] and not scene["cues"] and scene["caption"] is None
    assert (
        client.get(f"/api/projects/{scene['id']}/source.mp4").content
        == (DEMO_ASSETS / STYLE_FILENAME).read_bytes()
    )
    assert client.post("/api/demo?scene=robots").status_code == 422


def test_manual_upload_bind_and_action_work_without_ai(client, demo_video):
    with demo_video.open("rb") as source:
        result = client.post("/api/projects", files={"file": ("film.mp4", source, "video/mp4")})
    assert result.status_code == 201, result.text
    scene = result.json()
    assert not scene["objects"] and not scene["cues"]
    bound = client.post(
        f"/api/projects/{scene['id']}/objects",
        json={
            "revision": 0,
            "name": "My character",
            "box": {"time": 0, "x": 0.1, "y": 0.3, "width": 0.2, "height": 0.5},
        },
    )
    assert bound.status_code == 200, bound.text
    bound = bound.json()
    assert not bound["cues"]
    response = client.post(
        f"/api/projects/{scene['id']}/cues",
        json={
            "revision": bound["revision"],
            "object_id": bound["objects"][0]["id"],
            "kind": "impact",
            "time": 2,
        },
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["cues"]) == 1
    unavailable = client.post(
        f"/api/projects/{scene['id']}/analyze", json={"revision": 2, "brief": "Tiny adventure"}
    )
    assert unavailable.status_code == 503
    assert "manually" in unavailable.json()["detail"]


def test_recording_export_and_reimport_preserve_editability_and_pcm(client, tmp_path):
    scene = create_scene(client)
    sound = np.concatenate(
        [
            np.zeros(SAMPLE_RATE // 3),
            np.sin(2 * np.pi * 440 * np.arange(SAMPLE_RATE // 4) / SAMPLE_RATE)
            * np.exp(-np.arange(SAMPLE_RATE // 4) / 3000),
            np.zeros(SAMPLE_RATE // 3),
        ]
    )
    uploaded = client.post(
        f"/api/projects/{scene['id']}/assets",
        data={"revision": 0},
        files={"file": ("mug tap.wav", wav_bytes(sound), "audio/wav")},
    )
    assert uploaded.status_code == 200, uploaded.text
    scene = uploaded.json()
    asset = scene["assets"][-1]
    assert asset["duration"] < 0.5
    assigned = client.post(
        f"/api/projects/{scene['id']}/edit",
        json={
            "revision": scene["revision"],
            "object_id": "pour",
            "operations": [{"type": "set_sound", "asset_id": asset["id"], "kind": "movement"}],
        },
    )
    assert assigned.status_code == 200, assigned.text
    scene = assigned.json()
    result = client.post(
        f"/api/projects/{scene['id']}/exports", json={"revision": scene["revision"]}
    )
    assert result.status_code == 200, result.text
    rendered = probe(
        tmp_path / "media" / scene["id"] / "exports" / result.json()["id"] / "film.mp4"
    )
    assert (rendered.width, rendered.height) == (
        scene["media"]["width"],
        scene["media"]["height"],
    )
    assert rendered.duration == pytest.approx(scene["media"]["duration"], abs=0.05)
    download = client.get(result.json()["bundle_url"])
    assert download.status_code == 200
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        names = archive.namelist()
        assert all(name in names for name in ("source.mp4", "film.mp4", "mix.wav", "project.json"))
        layers = [name for name in names if name.startswith("layers/")]
        assert len(layers) == 3
        editable = json.loads(archive.read("project.json"))
        assert editable["cues"] == scene["cues"]
        assert scene["analysis_note"] in archive.read("README.txt").decode()
        original_asset = archive.read(f"assets/{asset['id']}.wav")
        with wave.open(io.BytesIO(archive.read(layers[0]))) as audio:
            assert audio.getnchannels() == 2
            assert audio.getframerate() == SAMPLE_RATE
            assert audio.getnframes() == round(rendered.duration * SAMPLE_RATE)
    restored = client.post(
        "/api/projects/import", files={"file": ("backup.zip", download.content, "application/zip")}
    )
    assert restored.status_code == 201, restored.text
    restored = restored.json()
    assert restored["id"] != scene["id"]
    assert restored["cues"] == scene["cues"]
    assert restored["objects"] == scene["objects"]
    assert restored["revision"] == 0
    assert (
        client.get(f"/api/projects/{restored['id']}/assets/{asset['id']}.wav").content
        == original_asset
    )


def test_invalid_media_and_oversized_bundle_leave_no_project(client, tmp_path):
    before = len(client.get("/api/projects").json())
    response = client.post(
        "/api/projects", files={"file": ("fake.mp4", b"not a video", "video/mp4")}
    )
    assert response.status_code == 422
    playlist = b"#EXTM3U\n#EXTINF:12,\nfile:///home/another-workspace/source.mp4\n"
    response = client.post("/api/projects", files={"file": ("playlist.mp4", playlist, "video/mp4")})
    assert response.status_code == 422
    response = client.post(
        "/api/projects/import", files={"file": ("invalid.zip", b"invalid", "application/zip")}
    )
    assert response.status_code == 422
    assert len(client.get("/api/projects").json()) == before
    assert list((tmp_path / "media").iterdir()) == []


def test_analysis_frames_have_actual_frame_timestamps(demo_video):
    metadata = probe(demo_video)
    frames = analysis_frames(demo_video, metadata.duration, count=6)
    assert len(frames) == 6
    assert frames[0]["time"] == 0
    assert frames[-1]["time"] == pytest.approx(
        (round(metadata.duration * metadata.fps) - 1) / metadata.fps
    )
    assert all(
        abs(frame["time"] * metadata.fps - round(frame["time"] * metadata.fps)) < 0.00001
        for frame in frames
    )
