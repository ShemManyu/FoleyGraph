import base64
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import imageio_ffmpeg
import numpy as np

from server.audio import SAMPLE_RATE, SoundLibrary, mix_layers, read_wav, render_layers, wav_bytes
from server.models import Media, Project, new_id

INPUT_FORMATS = "mov,mp4,m4a,3gp,3g2,mj2,matroska,webm,avi,wav,mp3,ogg,flac,aac"


def ffmpeg() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def run_ffmpeg(arguments: list[str], timeout: int = 120):
    try:
        result = subprocess.run(
            [ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *arguments],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Media processing timed out. Try a smaller, simpler clip.") from exc
    if result.returncode:
        raise ValueError(
            "This media could not be decoded. Please try an MP4 video or a WAV/MP3 sound."
        )
    return result


def probe(path: Path, filename: str = "scene.mp4") -> Media:
    result = subprocess.run(
        [
            ffmpeg(),
            "-hide_banner",
            "-nostdin",
            "-protocol_whitelist",
            "file,pipe",
            "-format_whitelist",
            INPUT_FORMATS,
            "-i",
            str(path),
        ],
        capture_output=True,
        timeout=20,
        check=False,
    )
    description = result.stderr.decode(errors="replace")
    duration = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", description)
    video = next((line for line in description.splitlines() if "Video:" in line), "")
    dimensions = re.search(r"(?:,|\s)(\d{2,5})x(\d{2,5})(?:[,\s])", video)
    fps = re.search(r"(\d+(?:\.\d+)?) fps", video)
    if not duration or not dimensions or not fps:
        raise ValueError("Upload a playable video with a known duration and frame rate.")
    seconds = int(duration[1]) * 3600 + int(duration[2]) * 60 + float(duration[3])
    if seconds > 20.05:
        raise ValueError("The studio supports one clip up to 20 seconds. Trim the video first.")
    return Media(
        duration=seconds,
        fps=float(fps[1]),
        width=int(dimensions[1]),
        height=int(dimensions[2]),
        filename=Path(filename).name[:150],
        has_audio="Audio:" in description,
    )


def normalize_video(source: Path, target: Path, filename: str) -> Media:
    metadata = probe(source, filename)
    if metadata.duration < 0.2:
        raise ValueError("The video needs to be at least 0.2 seconds long.")
    target.parent.mkdir(parents=True, exist_ok=True)
    fps = min(metadata.fps, 60)
    run_ffmpeg(
        [
            "-protocol_whitelist",
            "file,pipe",
            "-format_whitelist",
            INPUT_FORMATS,
            "-threads",
            "2",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-an",
            "-t",
            "20",
            "-vf",
            "scale=w='min(1280,iw)':h='min(1280,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
            "-r",
            str(fps),
            "-c:v",
            "libx264",
            "-threads",
            "2",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(target),
        ]
    )
    normalized = probe(target, filename)
    if metadata.has_audio:
        run_ffmpeg(
            [
                "-protocol_whitelist",
                "file,pipe",
                "-format_whitelist",
                INPUT_FORMATS,
                "-i",
                str(source),
                "-map",
                "0:a:0",
                "-vn",
                "-t",
                str(normalized.duration),
                "-af",
                f"aresample=async=1:first_pts=0,apad,atrim=duration={normalized.duration}",
                "-ac",
                "2",
                "-ar",
                str(SAMPLE_RATE),
                "-c:a",
                "pcm_s16le",
                str(target.parent / "source-audio.wav"),
            ]
        )
        normalized.has_audio = True
    return normalized


def normalize_audio(source: Path, target: Path, max_duration: float = 5) -> float:
    target.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-protocol_whitelist",
            "file,pipe",
            "-format_whitelist",
            INPUT_FORMATS,
            "-threads",
            "2",
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-vn",
            "-t",
            str(max_duration),
            "-ac",
            "1",
            "-ar",
            "48000",
            "-c:a",
            "pcm_s16le",
            str(target),
        ],
        timeout=45,
    )
    samples = read_wav(target)
    peak = float(np.max(np.abs(samples))) if len(samples) else 0
    active = np.flatnonzero(np.abs(samples) > max(0.001, peak * 0.015))
    if not len(active):
        raise ValueError("No audible sound was found. Try a clearer recording.")
    start = max(0, int(active[0]) - round(0.005 * SAMPLE_RATE))
    end = min(len(samples), int(active[-1]) + round(0.08 * SAMPLE_RATE))
    samples = samples[start:end] * (0.55 / max(peak, 0.001))
    target.write_bytes(wav_bytes(samples))
    duration = len(samples) / SAMPLE_RATE
    if duration < 0.04:
        raise ValueError("The recording is too short. Record at least 40 milliseconds.")
    return duration


def analysis_frames(path: Path, duration: float, count: int = 24) -> list[dict]:
    frames = []
    fps = probe(path).fps
    last_frame = max(0, round(duration * fps) - 1)
    indices = sorted({round(index * last_frame / max(1, count - 1)) for index in range(count)})
    with tempfile.TemporaryDirectory(prefix="foleygraph-frames-") as folder:
        target = Path(folder)
        selection = "+".join(f"eq(n\\,{index})" for index in indices)
        run_ffmpeg(
            [
                "-protocol_whitelist",
                "file,pipe",
                "-threads",
                "2",
                "-i",
                str(path),
                "-vf",
                f"select={selection},scale=640:-2",
                "-fps_mode",
                "vfr",
                "-frames:v",
                str(count),
                "-q:v",
                "4",
                "-threads",
                "2",
                str(target / "%03d.jpg"),
            ]
        )
        for index, frame in enumerate(sorted(target.glob("*.jpg"))):
            frames.append(
                {
                    "time": indices[index] / fps,
                    "image": base64.b64encode(frame.read_bytes()).decode(),
                }
            )
    return frames


def render_export(project: Project, library: SoundLibrary, folder: Path) -> dict:
    from server.visual import prepare_preview

    export_id = new_id()
    target = folder / "exports" / export_id
    target.mkdir(parents=True, exist_ok=True)
    try:
        layers = render_layers(project, library)
        for obj in project.objects:
            (target / f"layer-{obj.id}.wav").write_bytes(wav_bytes(layers[obj.id]))
        if project.music:
            (target / "music.wav").write_bytes(wav_bytes(layers[""]))
        if project.media.has_audio and not project.source_audio_muted:
            (target / "original.wav").write_bytes(wav_bytes(layers[":source"]))
        (target / "mix.wav").write_bytes(wav_bytes(mix_layers(layers, project.media.duration)))
        run_ffmpeg(
            [
                "-protocol_whitelist",
                "file,pipe",
                "-i",
                str(prepare_preview(project, folder)),
                "-i",
                str(target / "mix.wav"),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-t",
                str(project.media.duration),
                "-movflags",
                "+faststart",
                str(target / "film.mp4"),
            ]
        )
        portable = project.model_copy(deep=True)
        portable.undo_revisions = []
        (target / "project.json").write_text(portable.model_dump_json(indent=2), encoding="utf-8")
        notes = [
            "FoleyGraph editable scene bundle",
            f"Project: {project.name}",
            f"Revision: {project.revision}",
            "",
            "film.mp4: finished video with the FoleyGraph mix",
            "source.mp4: normalized silent source",
            "mix.wav: stereo mix, 48 kHz / 16-bit PCM",
            "layers/: isolated object sounds, plus active music and original audio",
            "project.json: editable graph, visual selections, music, cue timing and tracking",
            "assets/: creator recordings and original procedural CC0 library sounds used here",
            "",
            "Import this ZIP into FoleyGraph to reopen the editable scene.",
            "source-audio.wav, when present: the original soundtrack, not separated into voices and music.",
            "Ambient music is original procedural FoleyGraph music, dedicated to CC0.",
            "Only the master mix is peak-limited. Isolated layers preserve their own gain.",
            "Imported creator recordings remain subject to their owner's rights.",
            "",
            "Source and project notes:",
            project.source_credit,
            project.analysis_note,
        ]
        with zipfile.ZipFile(target / "bundle.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(target / "film.mp4", "film.mp4")
            archive.write(folder / "source.mp4", "source.mp4")
            if project.media.has_audio:
                archive.write(folder / "source-audio.wav", "source-audio.wav")
            archive.write(target / "mix.wav", "mix.wav")
            archive.write(target / "project.json", "project.json")
            for obj in project.objects:
                slug = re.sub(r"[^a-zA-Z0-9_-]", "-", obj.name).strip("-") or "object"
                archive.write(target / f"layer-{obj.id}.wav", f"layers/{slug}-{obj.id[:6]}.wav")
            if project.music:
                archive.write(target / "music.wav", "layers/ambient-music.wav")
            if project.media.has_audio and not project.source_audio_muted:
                archive.write(target / "original.wav", "layers/original-audio.wav")
            for asset_id in sorted(
                {cue.asset_id for cue in project.cues} | {a.id for a in project.assets}
            ):
                archive.write(library.path(project, asset_id), f"assets/{asset_id}.wav")
            archive.writestr("README.txt", "\n".join(notes))
        (target / "manifest.json").write_text(
            json.dumps({"revision": project.revision, "id": export_id}), encoding="ascii"
        )
        return {"id": export_id, "revision": project.revision}
    except Exception:
        shutil.rmtree(target)
        raise


def import_bundle(source: Path, data_dir: Path, library: SoundLibrary) -> Project:
    with zipfile.ZipFile(source) as archive:
        entries = archive.infolist()
        if len(entries) > 160 or sum(item.file_size for item in entries) > 150 * 1024 * 1024:
            raise ValueError("This project bundle is too large.")
        if len({item.filename for item in entries}) != len(entries):
            raise ValueError("Project bundles cannot contain duplicate paths.")
        for name in ("project.json", "source.mp4"):
            if name not in archive.namelist():
                raise ValueError("Choose a FoleyGraph ZIP containing project.json and source.mp4.")
        if archive.getinfo("project.json").file_size > 256_000:
            raise ValueError("The editable project document is too large.")
        project = Project.model_validate_json(archive.read("project.json"))
        project.id = new_id()
        project.revision = 0
        project.undo_revisions = []
        folder = data_dir / "media" / project.id
        folder.mkdir(parents=True)
        try:
            # Never extract arbitrary archive paths into the filesystem.
            with archive.open("source.mp4") as incoming, (folder / "source.mp4").open("wb") as out:
                shutil.copyfileobj(incoming, out)
            actual = probe(folder / "source.mp4", project.media.filename)
            if abs(actual.duration - project.media.duration) > 0.06:
                raise ValueError("The source video does not match the project duration.")
            if abs(actual.fps - project.media.fps) > 0.02:
                raise ValueError("The source video does not match the project frame rate.")
            if (actual.width, actual.height) != (project.media.width, project.media.height):
                raise ValueError("The source video does not match the project dimensions.")
            if project.media.has_audio:
                if (
                    "source-audio.wav" not in archive.namelist()
                    or archive.getinfo("source-audio.wav").file_size > 4_000_100
                ):
                    raise ValueError("The original soundtrack is missing or too large.")
                original = folder / "source-audio.wav"
                original.write_bytes(archive.read("source-audio.wav"))
                samples = read_wav(original, mono=False)
                if (
                    samples.ndim != 2
                    or samples.shape[1] != 2
                    or abs(len(samples) / SAMPLE_RATE - project.media.duration) > 0.05
                ):
                    raise ValueError("The original soundtrack does not match the video.")
            for asset in project.assets:
                name = f"assets/{asset.id}.wav"
                if name not in archive.namelist() or archive.getinfo(name).file_size > 2_000_000:
                    raise ValueError("A creator recording is missing or too large.")
                (folder / "assets").mkdir(exist_ok=True)
                sound_path = folder / "assets" / f"{asset.id}.wav"
                sound_path.write_bytes(archive.read(name))
                samples = read_wav(sound_path)
                asset.duration = len(samples) / SAMPLE_RATE
                if not 0.04 <= asset.duration <= 5.05:
                    raise ValueError(
                        "Creator recordings must be between 40 milliseconds and 5 seconds."
                    )
            library.validate(project)
            return Project.model_validate(project.model_dump())
        except Exception:
            shutil.rmtree(folder)
            raise
