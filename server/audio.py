import hashlib
import io
import math
import threading
import wave
from pathlib import Path

import numpy as np

from server.models import Project, SceneObject

SAMPLE_RATE = 48000
PROFILES = {
    "wood": "Warm wood",
    "metal": "Little machine",
    "stone": "Heavy stone",
    "soft": "Soft felt",
    "glass": "Delicate glass",
    "paper": "Crisp paper",
    "water": "Water drops",
    "synth": "Space explorer",
}
KINDS = ("footstep", "impact", "movement", "ambience")
DURATIONS = {"footstep": 0.26, "impact": 0.65, "movement": 1.15, "ambience": 4.0}


def wav_bytes(samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> bytes:
    data = np.clip(np.round(samples * 32767), -32768, 32767).astype("<i2")
    with io.BytesIO() as buffer:
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(1 if data.ndim == 1 else data.shape[1])
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(data.tobytes())
        return buffer.getvalue()


def read_wav(path: Path, mono: bool = True) -> np.ndarray:
    with wave.open(str(path), "rb") as handle:
        if handle.getsampwidth() != 2 or handle.getframerate() != SAMPLE_RATE:
            raise ValueError("Sound assets must be 48 kHz, 16-bit PCM WAV files.")
        values = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2").astype(
            np.float32
        )
        if handle.getnchannels() > 1:
            values = values.reshape(-1, handle.getnchannels())
            if mono:
                values = values.mean(axis=1)
        return values / 32768


def ambient_music(duration: float) -> np.ndarray:
    size = round(duration * SAMPLE_RATE)
    sound = np.zeros((size, 2), dtype=np.float64)
    chords = ((50, 57, 60, 64), (46, 53, 57, 60), (53, 60, 64, 69), (48, 55, 59, 62))
    for index in range(4):
        start = round(index * duration / 4 * SAMPLE_RATE)
        length = min(size - start, round((duration / 4 + 1.8) * SAMPLE_RATE))
        time = np.arange(length) / SAMPLE_RATE
        envelope = (1 - np.exp(-time * 2)) * np.minimum(1, (length / SAMPLE_RATE - time) / 1.6)
        for voice, midi in enumerate(chords[index]):
            frequency = 440 * 2 ** ((midi - 69) / 12)
            for channel, detune in enumerate((-0.0015, 0.0015)):
                tone = np.sin(2 * np.pi * frequency * (1 + detune) * time + voice * 0.7)
                tone += 0.16 * np.sin(2 * np.pi * frequency * 2 * time)
                tone += 0.04 * np.sin(2 * np.pi * frequency * 3 * time)
                sound[start : start + length, channel] += tone * envelope / 4
    edge = min(round(0.7 * SAMPLE_RATE), size // 2)
    sound[:edge] *= np.linspace(0, 1, edge)[:, None]
    sound[-edge:] *= np.linspace(1, 0, edge)[:, None]
    sound *= 0.55 / max(0.001, float(np.max(np.abs(sound))))
    return sound.astype(np.float32)


def synthesize(profile: str, kind: str) -> np.ndarray:
    duration = DURATIONS[kind]
    time = np.arange(round(duration * SAMPLE_RATE), dtype=np.float64) / SAMPLE_RATE
    seed = int.from_bytes(hashlib.sha256(f"{profile}:{kind}:v1".encode()).digest()[:8], "big")
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, 1, len(time))
    pitch = {
        "wood": 180,
        "metal": 720,
        "stone": 85,
        "soft": 110,
        "glass": 1550,
        "paper": 450,
        "water": 1050,
        "synth": 300,
    }[profile]
    if kind == "ambience":
        frequencies = np.fft.rfftfreq(len(time), 1 / SAMPLE_RATE)
        sound = np.fft.irfft(np.fft.rfft(noise) / np.maximum(1, frequencies / 80), len(time))
        sound += 0.03 * np.sin(2 * np.pi * (pitch / 4) * time)
        sound *= 0.7 + 0.3 * np.sin(np.pi * time / duration) ** 2
    else:
        decay = {"footstep": 22, "impact": 9, "movement": 4}[kind]
        tone = np.sin(2 * np.pi * pitch * time) * np.exp(-decay * time)
        if profile in ("metal", "glass", "synth"):
            sound = tone + 0.5 * np.sin(2 * np.pi * pitch * 2.71 * time) * np.exp(
                -decay * 0.65 * time
            )
            sound += noise * np.exp(-90 * time) * 0.4
        elif profile == "water":
            sound = np.sin(2 * np.pi * (pitch * time - 600 * time**2)) * np.exp(-decay * time)
            sound += 0.12 * noise * np.exp(-40 * time)
        elif profile in ("soft", "paper"):
            window = np.hanning(15 if profile == "soft" else 3)
            sound = np.convolve(noise, window / window.sum(), mode="same") * np.exp(-decay * time)
        else:
            sound = tone * 0.7 + np.convolve(noise, np.ones(7) / 7, mode="same") * np.exp(
                -decay * 2 * time
            )
        if kind == "movement":
            sound *= 0.35 + 0.65 * np.sin(2 * np.pi * 7 * time) ** 2
    edge = min(240, len(sound) // 2)
    sound[:edge] *= np.linspace(0, 1, edge)
    sound[-edge:] *= np.linspace(1, 0, edge)
    sound /= max(float(np.max(np.abs(sound))), 0.001)
    return (sound * (0.17 if kind == "ambience" else 0.55)).astype(np.float32)


class SoundLibrary:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.samples_dir = data_dir / "samples"
        self.music_lock = threading.Lock()
        self.catalog = [
            {
                "id": f"{profile}-{kind}",
                "name": f"{label} {kind}",
                "profile": profile,
                "kind": kind,
                "duration": DURATIONS[kind],
                "source": "Original procedural FoleyGraph sample",
                "license": "CC0-1.0",
            }
            for profile, label in PROFILES.items()
            for kind in KINDS
        ]
        self.ids = {item["id"] for item in self.catalog}

    def prepare(self):
        self.samples_dir.mkdir(parents=True, exist_ok=True)
        for item in self.catalog:
            path = self.samples_dir / f"{item['id']}.wav"
            if not path.exists():
                path.write_bytes(wav_bytes(synthesize(item["profile"], item["kind"])))

    def path(self, project: Project, asset_id: str) -> Path:
        if asset_id in self.ids:
            return self.samples_dir / f"{asset_id}.wav"
        if any(asset.id == asset_id for asset in project.assets):
            return self.data_dir / "media" / project.id / "assets" / f"{asset_id}.wav"
        raise ValueError("Choose a sound from the library or this project's recordings.")

    def validate(self, project: Project):
        for obj in project.objects:
            for asset_id in obj.sound_overrides.values():
                self.path(project, asset_id)
        for cue in project.cues:
            self.path(project, cue.asset_id)

    def music_path(self, project: Project) -> Path:
        path = (
            self.data_dir
            / "scores"
            / f"ambient-v1-{round(project.media.duration * SAMPLE_RATE)}.wav"
        )
        with self.music_lock:
            if not path.is_file():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(wav_bytes(ambient_music(project.media.duration)))
        return path


def pan_curve(obj: SceneObject, times: np.ndarray) -> np.ndarray:
    if not obj.keyframes:
        return np.zeros(len(times))
    return np.clip(
        np.interp(
            times,
            [frame.time for frame in obj.keyframes],
            [(frame.x + frame.width / 2) * 2 - 1 for frame in obj.keyframes],
        ),
        -1,
        1,
    )


def render_layers(project: Project, library: SoundLibrary) -> dict[str, np.ndarray]:
    size = round(project.media.duration * SAMPLE_RATE)
    layers = {obj.id: np.zeros((size, 2), dtype=np.float32) for obj in project.objects}
    objects = {obj.id: obj for obj in project.objects}
    cache: dict[str, np.ndarray] = {}
    for cue in sorted(project.cues, key=lambda event: (event.time, event.id)):
        obj = objects[cue.object_id]
        if cue.muted or obj.muted:
            continue
        if cue.asset_id not in cache:
            cache[cue.asset_id] = read_wav(library.path(project, cue.asset_id))
        original = cache[cue.asset_id]
        output_size = round(cue.duration * SAMPLE_RATE)
        source_positions = np.arange(output_size) * cue.playback_rate
        if cue.kind == "ambience":
            sound = np.interp(source_positions % len(original), np.arange(len(original)), original)
        else:
            sound = np.interp(source_positions, np.arange(len(original)), original, left=0, right=0)
        if cue.lowpass_hz is not None:
            frequencies = np.fft.rfftfreq(len(sound), 1 / SAMPLE_RATE)
            sound = np.fft.irfft(
                np.fft.rfft(sound) / np.sqrt(1 + (frequencies / cue.lowpass_hz) ** 4),
                len(sound),
            )
        # Fade the audible sample, not the padded silence after a one-shot.
        audible = (
            output_size
            if cue.kind == "ambience"
            else min(output_size, math.ceil(len(original) / cue.playback_rate))
        )
        fade_in = min(round(cue.fade_in * SAMPLE_RATE), audible)
        fade_out = min(round(cue.fade_out * SAMPLE_RATE), audible)
        if fade_in:
            sound[:fade_in] *= np.linspace(0, 1, fade_in)
        if fade_out:
            sound[audible - fade_out : audible] *= np.linspace(1, 0, fade_out)
        start = round(cue.time * SAMPLE_RATE)
        count = min(len(sound), size - start)
        if count <= 0:
            continue
        times = cue.time + np.arange(count) / SAMPLE_RATE
        pan = np.full(count, cue.pan) if cue.pan is not None else pan_curve(obj, times)
        angle = (pan + 1) * np.pi / 4
        gain = 10 ** ((cue.gain_db + obj.gain_db) / 20)
        layers[obj.id][start : start + count, 0] += sound[:count] * np.cos(angle) * gain
        layers[obj.id][start : start + count, 1] += sound[:count] * np.sin(angle) * gain
    if project.music:
        # An empty key cannot collide with a validated scene-object ID.
        layers[""] = read_wav(library.music_path(project), mono=False) * 10 ** (
            project.music.gain_db / 20
        )
    if project.media.has_audio and not project.source_audio_muted:
        layers[":source"] = read_wav(
            library.data_dir / "media" / project.id / "source-audio.wav", mono=False
        )
    return layers


def mix_layers(layers: dict[str, np.ndarray], duration: float) -> np.ndarray:
    mix = np.zeros((round(duration * SAMPLE_RATE), 2), dtype=np.float32)
    for layer in layers.values():
        mix += layer
    peak = float(np.max(np.abs(mix))) if mix.size else 0
    if peak > 0.98:
        mix *= 0.98 / peak
    return mix
