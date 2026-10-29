"""Prepare the licensed stock demo and original sound assets, not run at app startup."""

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from server.audio import SAMPLE_RATE, wav_bytes
from server.media import run_ffmpeg

ROOT = Path(__file__).resolve().parent.parent
DESTINATION = ROOT / "server" / "assets" / "demo"
SOURCE_URL = "https://www.pexels.com/video/pouring-water-into-coffee-cup-14364305/"
DOWNLOAD_URL = "https://videos.pexels.com/video-files/14364305/14364305-hd_1080_1920_25fps.mp4"


def save_sound(name: str, values: np.ndarray, peak: float):
    values = values.astype(np.float64)
    edge = min(960, len(values) // 2)
    values[:edge] *= np.linspace(0, 1, edge)
    values[-edge:] *= np.linspace(1, 0, edge)
    values *= peak / max(0.001, float(np.max(np.abs(values))))
    (DESTINATION / f"{name}.wav").write_bytes(wav_bytes(values))


def sounds():
    rng = np.random.default_rng(20261029)
    time = np.arange(4 * SAMPLE_RATE) / SAMPLE_RATE
    noise = rng.normal(0, 1, len(time))
    water = np.convolve(noise, np.hanning(13) / np.hanning(13).sum(), mode="same")
    water *= 0.6 + 0.15 * np.sin(2 * np.pi * 3.7 * time) + 0.1 * np.sin(2 * np.pi * 11 * time)
    for onset in rng.uniform(0, 3.8, 95):
        age = time - onset
        active = (age >= 0) & (age < 0.12)
        frequency = rng.uniform(450, 1800)
        water[active] += (
            0.06
            * np.sin(2 * np.pi * (frequency * age[active] - 1600 * age[active] ** 2))
            * np.exp(-age[active] * 38)
        )
    save_sound("velvet-pour", water, 0.55)

    time = np.arange(round(0.55 * SAMPLE_RATE)) / SAMPLE_RATE
    cup = sum(
        weight * np.sin(2 * np.pi * frequency * time) * np.exp(-decay * time)
        for frequency, weight, decay in ((620, 0.5, 16), (1730, 0.3, 21), (2910, 0.1, 27))
    )
    cup += rng.normal(0, 0.08, len(time)) * np.exp(-time * 150)
    save_sound("ceramic-drop", cup, 0.28)

    time = np.arange(4 * SAMPLE_RATE) / SAMPLE_RATE
    noise = rng.normal(0, 1, len(time))
    frequency = np.fft.rfftfreq(len(time), 1 / SAMPLE_RATE)
    room = np.fft.irfft(np.fft.rfft(noise) / np.maximum(1, frequency / 140), len(time))
    room *= 0.85 + 0.1 * np.sin(2 * np.pi * 0.3 * time)
    save_sound("cafe-air", room, 0.16)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, required=True, help=f"Downloaded from {DOWNLOAD_URL}"
    )
    args = parser.parse_args()
    DESTINATION.mkdir(parents=True, exist_ok=True)

    overlay = Image.new("RGBA", (720, 1280))
    draw = ImageDraw.Draw(overlay)
    for y in range(880, 1280):
        draw.line((0, y, 720, y), fill=(24, 15, 8, round((y - 880) / 400 * 135)))
    draw.text((43, 1070), "slow mornings.", font=ImageFont.load_default(size=66), fill="#fff5e5")
    draw.text(
        (47, 1160),
        "A LITTLE COFFEE. A LITTLE QUIET.",
        font=ImageFont.load_default(size=18),
        fill="#f3dfc5",
    )
    overlay_path = DESTINATION / "title.png"
    overlay.save(overlay_path)
    try:
        run_ffmpeg(
            [
                "-ss",
                "0.24",
                "-i",
                str(args.source),
                "-i",
                str(overlay_path),
                "-filter_complex",
                "[0:v]crop=900:1600:0:320,scale=720:1280,fps=24,"
                "eq=contrast=1.04:brightness=0.005:saturation=0.86[graded];"
                "[graded][1:v]overlay=0:0,format=yuv420p[out]",
                "-map",
                "[out]",
                "-t",
                "8",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "22",
                "-threads",
                "2",
                "-movflags",
                "+faststart",
                str(DESTINATION / "morning-ritual.mp4"),
            ]
        )
    finally:
        overlay_path.unlink(missing_ok=True)
    run_ffmpeg(
        [
            "-i",
            str(DESTINATION / "morning-ritual.mp4"),
            "-frames:v",
            "1",
            "-vf",
            "scale=450:800",
            str(ROOT / "web" / "public" / "demo-poster.jpg"),
        ]
    )
    sounds()
    (DESTINATION / "credits.json").write_text(
        json.dumps(
            {
                "video": {
                    "title": "Pouring Water into Coffee Cup",
                    "creator": "WIERZBA PH",
                    "source": SOURCE_URL,
                    "download": DOWNLOAD_URL,
                    "license": "Pexels License",
                    "license_url": "https://www.pexels.com/license/",
                    "changes": "Eight-second crop, portrait reframing, color treatment, original title, and replacement sound design.",
                },
                "sound": {
                    "creator": "FoleyGraph",
                    "license": "CC0-1.0",
                    "description": "Original procedural pour, ceramic resonance, and room tone. Not field recordings.",
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print("Prepared the eight-second portrait reel, poster, sounds, and license credits.")


if __name__ == "__main__":
    main()
