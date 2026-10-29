"""Download the verified CPU bundle, or reproduce its SAM 2.1 ONNX conversion.

SAM 2 model and image-predictor conventions: Copyright (c) Meta Platforms, Inc.
and affiliates. Apache-2.0, retained in LICENSES/SAM2.txt.
"""

import argparse
import hashlib
import importlib.metadata
import json
import shutil
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "sam2.1-hiera-tiny"
OUTPUT = ROOT / "server" / "assets" / "models" / NAME
SOURCE = "2b90b9f5ceec907a1c18123530e92e794ad901a4"
CHECKPOINT = "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_tiny.pt"
CHECKPOINT_SHA256 = "7402e0d864fa82708a20fbd15bc84245c2f26dff0eb43a4b5b93452deb34be69"
RELEASE = "https://foleygraphfokas1029.z20.web.core.windows.net/models/meta-sam2.1-cpu-v2"
FILES = {
    "encoder.onnx": "1d8d9009d2ec9dc4380a2509822726a692e515859cd6e3f3f855a5d632fd9565",
    "decoder.onnx": "69921d6f3303706d9e23202561d42536fc8b77f02d862b65424998ac0d64f8d1",
}
SIZE = 512


def checksum(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def download(url: str, path: Path, expected: str | None = None):
    deadline = time.monotonic() + 900
    total = 0
    progress = 0
    with urllib.request.urlopen(url, timeout=30) as response, path.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > 200 * 1024 * 1024 or time.monotonic() > deadline:
                raise RuntimeError("The model download exceeded its size or time limit.")
            output.write(chunk)
            if total // (10 * 1024 * 1024) > progress:
                progress = total // (10 * 1024 * 1024)
                print(f"{path.name}: {total / 1024**2:.0f} MiB downloaded.", flush=True)
    if expected and checksum(path) != expected:
        raise ValueError("The downloaded model checksum does not match the reviewed release.")


def export_models(directory: Path, checkpoint: Path):
    import onnx
    import torch
    from sam2.build_sam import build_sam2

    source = json.loads(
        importlib.metadata.distribution("SAM-2").read_text("direct_url.json") or "{}"
    )
    if source.get("vcs_info", {}).get("commit_id") != SOURCE:
        raise ValueError("Install the pinned official SAM 2 source revision before exporting.")
    if torch.__version__.split("+")[0] != "2.7.1" or onnx.__version__ != "1.17.0":
        raise ValueError("Use Torch 2.7.1 and ONNX 1.17.0 for the reviewed conversion.")
    if not checkpoint.is_file():
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        download(CHECKPOINT, checkpoint, CHECKPOINT_SHA256)
    if checksum(checkpoint) != CHECKPOINT_SHA256:
        raise ValueError("The official SAM 2.1 checkpoint checksum does not match.")
    torch.set_num_threads(1)
    model = build_sam2(
        "configs/sam2.1/sam2.1_hiera_t.yaml",
        str(checkpoint),
        device="cpu",
        apply_postprocessing=False,
        hydra_overrides_extra=[f"++model.image_size={SIZE}"],
    ).eval()

    class Encoder(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.model = model

        def forward(self, image):
            backbone = self.model.forward_image(image)
            _, features, _, _ = self.model._prepare_backbone_features(backbone)
            if self.model.directly_add_no_mem_embed:
                features[-1] = features[-1] + self.model.no_mem_embed
            shapes = [(SIZE // stride, SIZE // stride) for stride in (4, 8, 16)]
            images = [
                feature.permute(1, 2, 0).view(1, -1, *shape)
                for feature, shape in zip(features, shapes, strict=True)
            ]
            return images[2], images[0], images[1]

    class Decoder(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.model = model

        def forward(self, embedding, high0, high1, coordinates, labels):
            sparse, dense = self.model.sam_prompt_encoder(
                points=(coordinates, labels), boxes=None, masks=None
            )
            masks, scores, _, _ = self.model.sam_mask_decoder(
                image_embeddings=embedding,
                image_pe=self.model.sam_prompt_encoder.get_dense_pe(),
                sparse_prompt_embeddings=sparse,
                dense_prompt_embeddings=dense,
                multimask_output=False,
                repeat_image=False,
                high_res_features=[high0, high1],
            )
            return masks, scores

    encoder, decoder = Encoder().eval(), Decoder().eval()
    image = torch.zeros((1, 3, SIZE, SIZE), dtype=torch.float32)
    coordinates = torch.tensor(
        [
            [
                [64, 64],
                [704, 704],
                [300, 300],
                [300, 500],
                [250, 350],
                [200, 600],
                [450, 450],
                [20, 20],
                [740, 740],
                [640, 50],
            ]
        ],
        dtype=torch.float32,
    )
    labels = torch.tensor([[2, 3, 1, 1, 1, 1, 1, 0, 0, 0]], dtype=torch.int32)
    with torch.inference_mode():
        features = encoder(image)
        torch.onnx.export(
            encoder,
            image,
            str(directory / "encoder.onnx"),
            input_names=["image"],
            output_names=["embedding", "high0", "high1"],
            opset_version=17,
            dynamo=False,
            external_data=False,
        )
        torch.onnx.export(
            decoder,
            (*features, coordinates, labels),
            str(directory / "decoder.onnx"),
            input_names=["embedding", "high0", "high1", "coordinates", "labels"],
            output_names=["logits", "scores"],
            opset_version=17,
            dynamic_axes={"coordinates": {1: "points"}, "labels": {1: "points"}},
            dynamo=False,
            external_data=False,
        )
    for name in FILES:
        onnx.checker.check_model(onnx.load(directory / name))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--export", action="store_true", help="Rebuild using optional Torch/SAM tools."
    )
    parser.add_argument(
        "--checkpoint", type=Path, default=ROOT / ".data" / "model-build" / "sam2.1_hiera_tiny.pt"
    )
    args = parser.parse_args()
    work = ROOT / ".data" / "model-build"
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="prepare-", dir=work) as temporary:
        directory = Path(temporary)
        if args.export:
            export_models(directory, args.checkpoint)
        else:
            for name, expected in FILES.items():
                existing = OUTPUT / name
                if existing.is_file() and checksum(existing) == expected:
                    shutil.copyfile(existing, directory / name)
                else:
                    print(f"Downloading {name}.", flush=True)
                    download(f"{RELEASE}/{name}", directory / name, expected)
        hashes = {name: checksum(directory / name) for name in FILES}
        license_path = ROOT / "LICENSES" / "SAM2.txt"
        license_path.parent.mkdir(exist_ok=True)
        if not license_path.is_file():
            download(
                f"https://raw.githubusercontent.com/facebookresearch/sam2/{SOURCE}/LICENSE",
                directory / "LICENSE",
            )
            shutil.copyfile(directory / "LICENSE", license_path)
        shutil.copyfile(license_path, directory / "LICENSE")
        manifest = {
            "model": NAME,
            "input_size": SIZE,
            "source_revision": SOURCE,
            "checkpoint_sha256": CHECKPOINT_SHA256,
            "files": hashes,
            "license": "Apache-2.0",
            "scope": "Image anchors only; temporal tracking is FoleyGraph's CPU implementation.",
        }
        (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        OUTPUT.mkdir(parents=True, exist_ok=True)
        for name in (*FILES, "LICENSE", "manifest.json"):
            (directory / name).replace(OUTPUT / name)
        print(json.dumps(manifest, indent=2))
        print("Prepared CPU model. Restart the application before using new masks.")


if __name__ == "__main__":
    main()
