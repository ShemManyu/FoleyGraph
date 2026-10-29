"""Exercise real Foundry inference through the local app, never the deployed service."""

import argparse
import io
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--speech-file", type=Path, help="Optional WAV of an original editing direction."
    )
    args = parser.parse_args()
    with httpx.Client(base_url=f"http://127.0.0.1:{args.port}", timeout=220) as client:
        configuration = client.get("/api/config")
        configuration.raise_for_status()
        if not configuration.json()["ai_available"]:
            raise RuntimeError("Start scripts/run_local.py --azure before this check.")
        created = client.post("/api/demo")
        created.raise_for_status()
        scene = created.json()
        root = f"/api/projects/{scene['id']}"

        def post(suffix: str, body: dict):
            response = client.post(f"{root}/{suffix}", json=body)
            if not response.is_success:
                raise RuntimeError(f"{suffix}: {response.status_code} {response.text}")
            return response.json()

        def stems(project):
            exported = post("exports", {"revision": project["revision"]})
            archive = client.get(exported["bundle_url"])
            archive.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
                return {
                    name: bundle.read(name)
                    for name in bundle.namelist()
                    if name.startswith("layers/")
                }

        try:
            baseline = stems(scene)
            directed = post(
                "direct",
                {
                    "revision": scene["revision"],
                    "instruction": "Make only the coffee pour's movement sounds metallic. Keep all cue times and the cup and cafe layers unchanged.",
                },
            )["project"]
            assert [cue for cue in directed["cues"] if cue["object_id"] != "pour"] == [
                cue for cue in scene["cues"] if cue["object_id"] != "pour"
            ]
            assert [cue["time"] for cue in directed["cues"]] == [
                cue["time"] for cue in scene["cues"]
            ]
            assert all(
                cue["asset_id"] == "metal-movement"
                for cue in directed["cues"]
                if cue["object_id"] == "pour"
            )
            after_stems = stems(directed)
            for name in baseline:
                if not name.endswith("-pour.wav"):
                    assert baseline[name] == after_stems[name], f"Untargeted PCM changed: {name}"
                else:
                    assert baseline[name] != after_stems[name]
            print(
                "PASS: real chat inferred the coffee pour without a selection; other exported WAVs are byte-identical.",
                flush=True,
            )

            impact = next(cue for cue in directed["cues"] if cue["object_id"] == "cup")
            shifted = post(
                "direct",
                {
                    "revision": directed["revision"],
                    "instruction": "Move only the ceramic cup's set-down impact exactly two frames earlier. Change nothing else.",
                },
            )["project"]
            changed_impact = next(cue for cue in shifted["cues"] if cue["id"] == impact["id"])
            assert (
                abs(changed_impact["time"] - (impact["time"] - 2 / directed["media"]["fps"]))
                < 0.00001
            )
            assert [cue for cue in shifted["cues"] if cue["id"] != impact["id"]] == [
                cue for cue in directed["cues"] if cue["id"] != impact["id"]
            ]
            print(
                "PASS: real Foundry direction moved one impact exactly two frames earlier.",
                flush=True,
            )

            with tempfile.TemporaryDirectory(prefix="foleygraph-speech-") as directory:
                speech = args.speech_file
                if speech is None and shutil.which("say"):
                    speech = Path(directory) / "original-direction.wav"
                    subprocess.run(
                        [
                            "say",
                            "-o",
                            str(speech),
                            "--file-format=WAVE",
                            "--data-format=LEI16@48000",
                            "Make the coffee pour metallic, and leave the other layers unchanged.",
                        ],
                        check=True,
                    )
                if speech is not None:
                    with speech.open("rb") as audio:
                        transcription = client.post(
                            "/api/transcribe", files={"file": (speech.name, audio, "audio/wav")}
                        )
                    transcription.raise_for_status()
                    text = transcription.json()["text"].lower()
                    assert "pour" in text and "metal" in text, text
                    print(
                        "PASS: real Foundry transcription recognized the original spoken editing direction.",
                        flush=True,
                    )
                else:
                    raise RuntimeError(
                        "Provide --speech-file to complete the transcription check on this platform."
                    )

            analyzed = post(
                "analyze",
                {
                    "revision": shifted["revision"],
                    "brief": "An intimate cafe reel. A barista pours into a ceramic cup, then lifts the metal pitcher away. Find the visible objects and actual sound-producing actions. Quiet, tactile Foley with subtle room tone, no music.",
                },
            )
            assert 2 <= len(analyzed["objects"]) <= 3
            assert analyzed["cues"]
            assert all(obj["keyframes"] for obj in analyzed["objects"])
            identities = {obj["id"] for obj in analyzed["objects"]}
            assert all(cue["object_id"] in identities for cue in analyzed["cues"])
            print(
                f"PASS: real vision analysis proposed {len(identities)} distinct tracked objects "
                f"and {len(analyzed['cues'])} editable action cues.",
                flush=True,
            )
        finally:
            latest = client.get(root)
            if latest.is_success:
                client.request(
                    "DELETE", root, json={"revision": latest.json()["revision"]}
                ).raise_for_status()


if __name__ == "__main__":
    main()
