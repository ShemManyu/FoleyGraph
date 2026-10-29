"""Optional, verified SAM 2.1 image anchors, not the SAM video-memory predictor."""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

MODEL_NAME = "sam2.1-hiera-tiny"
MODEL_DIR = Path(__file__).parent / "assets" / "models" / MODEL_NAME
CHECKPOINT_SHA256 = "7402e0d864fa82708a20fbd15bc84245c2f26dff0eb43a4b5b93452deb34be69"
SOURCE_REVISION = "2b90b9f5ceec907a1c18123530e92e794ad901a4"
INPUT_SIZE = 768
INSTALL_MESSAGE = (
    "The Meta mask model is unavailable. Run scripts/prepare_meta_model.py and restart."
)


@lru_cache(maxsize=1)
def model_info() -> dict | None:
    manifest = MODEL_DIR / "manifest.json"
    if not manifest.is_file():
        return None
    try:
        data = json.loads(manifest.read_text())
        if (
            data["model"] != MODEL_NAME
            or data["input_size"] != INPUT_SIZE
            or data["checkpoint_sha256"] != CHECKPOINT_SHA256
            or data["source_revision"] != SOURCE_REVISION
            or set(data["files"]) != {"encoder.onnx", "decoder.onnx"}
        ):
            raise ValueError(INSTALL_MESSAGE)
        hashes = {}
        for name, expected in data["files"].items():
            with (MODEL_DIR / name).open("rb") as handle:
                actual = hashlib.file_digest(handle, "sha256").hexdigest()
            if actual != expected:
                raise ValueError(INSTALL_MESSAGE)
            hashes[name] = actual
        fingerprint = hashlib.sha256(
            json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return {
            "name": MODEL_NAME,
            "sha256": fingerprint,
            "input_size": INPUT_SIZE,
            "checkpoint_sha256": CHECKPOINT_SHA256,
            "source_revision": SOURCE_REVISION,
        }
    except (OSError, KeyError, TypeError, ValueError):
        raise ValueError(INSTALL_MESSAGE) from None


@lru_cache(maxsize=1)
def _sessions():
    if model_info() is None:
        raise ValueError(INSTALL_MESSAGE)
    try:
        import onnxruntime as ort
    except ImportError:
        raise ValueError("Install requirements.txt to enable Meta mask inference.") from None
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.enable_cpu_mem_arena = False
    options.enable_mem_pattern = False
    options.log_severity_level = 3
    return tuple(
        ort.InferenceSession(
            str(MODEL_DIR / name),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        for name in ("encoder.onnx", "decoder.onnx")
    )


def coverage_points(guide: np.ndarray, seeds: np.ndarray) -> list:
    height, width = guide.shape
    positive = seeds.tolist()
    safe = (guide > 0).astype(np.uint8)
    rows = np.flatnonzero(safe.any(axis=1))
    if not len(rows):
        return positive
    distance = cv2.distanceTransform(cv2.erode(safe, np.ones((5, 5), np.uint8)), cv2.DIST_L2, 3)
    bands = np.linspace(rows.min(), rows.max() + 1, 5).astype(int)
    for top, bottom in zip(bands[:-1], bands[1:], strict=True):
        if len(positive) >= 12:
            break
        if bottom <= top or not np.any(distance[top:bottom] > 2):
            continue
        y, x = np.unravel_index(np.argmax(distance[top:bottom]), distance[top:bottom].shape)
        positive.append([float(x / (width - 1)), float((top + y) / (height - 1))])
    return positive


def refine_mask(mask: np.ndarray, protected: np.ndarray) -> np.ndarray:
    height, width = mask.shape
    radius = max(1, round(max(height, width) / (INPUT_SIZE // 4)))
    pixels = np.round(protected.reshape(-1, 2) * [width - 1, height - 1]).astype(int)
    kernel = np.ones((radius * 2 + 1,) * 2, np.uint8)
    mask = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, kernel)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(1 - mask)
    fill = stats[:, cv2.CC_STAT_AREA] <= max(16, np.count_nonzero(mask) * 0.03)
    border = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    fill[border] = False
    fill[0] = False
    if len(pixels):
        fill[labels[pixels[:, 1], pixels[:, 0]]] = False
    mask |= fill[labels].astype(np.uint8)
    mask = cv2.dilate(mask, kernel)
    for x, y in pixels:
        cv2.circle(mask, (int(x), int(y)), radius, 0, -1)
    return mask * 255


def propagate_mask(mask: np.ndarray, previous_gray: np.ndarray, gray: np.ndarray) -> np.ndarray:
    height, width = gray.shape
    scale = min(1, 256 / max(height, width))
    size = (max(2, round(width * scale)), max(2, round(height * scale)))
    previous = cv2.resize(previous_gray, size, interpolation=cv2.INTER_AREA)
    current = cv2.resize(gray, size, interpolation=cv2.INTER_AREA)
    backward = cv2.calcOpticalFlowFarneback(current, previous, None, 0.5, 3, 15, 3, 5, 1.2, 0)
    backward = cv2.resize(backward, (width, height), interpolation=cv2.INTER_LINEAR)
    backward[:, :, 0] *= width / size[0]
    backward[:, :, 1] *= height / size[1]
    rows, columns = np.indices((height, width), dtype=np.float32)
    return cv2.remap(
        mask,
        columns + backward[:, :, 0],
        rows + backward[:, :, 1],
        cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
    )


def refine_tracked_mask(mask: np.ndarray, guide: np.ndarray) -> np.ndarray:
    count, labels, stats, _ = cv2.connectedComponentsWithStats((guide > 0).astype(np.uint8))
    covered = np.bincount(labels[(mask > 0) & (guide > 0)], minlength=count)
    supported = covered / np.maximum(1, stats[:, cv2.CC_STAT_AREA]) >= 0.95
    supported[0] = False
    radius = max(1, round(max(mask.shape) / (INPUT_SIZE // 4)))
    nearby = cv2.dilate(mask, np.ones((radius * 2 + 1,) * 2, np.uint8)) > 0
    return mask | ((supported[labels] & nearby & (guide > 0)).astype(np.uint8) * 255)


def predict_mask(
    frame: np.ndarray,
    polygon: np.ndarray,
    seeds: np.ndarray,
    protected: np.ndarray,
    guide: np.ndarray,
    model_sha256: str,
) -> np.ndarray:
    info = model_info()
    if info is None or info["sha256"] != model_sha256:
        raise ValueError(INSTALL_MESSAGE)
    if not len(seeds):
        raise ValueError("A Meta surface edit needs a grounded foreground point.")
    height, width = frame.shape[:2]
    normalized = polygon / [width - 1, height - 1]
    corners = [normalized.min(axis=0).tolist(), normalized.max(axis=0).tolist()]
    positive = coverage_points(guide, seeds)
    negative = protected.reshape(-1, 2).tolist()
    coordinates = np.array([corners + positive + negative], np.float32) * INPUT_SIZE
    labels = np.array([[2, 3] + [1] * len(positive) + [0] * len(negative)], dtype=np.int32)
    image = Image.fromarray(frame).resize((INPUT_SIZE, INPUT_SIZE), Image.Resampling.BILINEAR)
    values = np.asarray(image).astype(np.float32) / 255
    values = (values - np.array([0.485, 0.456, 0.406], np.float32)) / np.array(
        [0.229, 0.224, 0.225], np.float32
    )
    tensor = np.ascontiguousarray(values.transpose(2, 0, 1)[None])
    encoder, decoder = _sessions()
    embedding, high0, high1 = encoder.run(None, {"image": tensor})
    logits, scores = decoder.run(
        None,
        {
            "embedding": embedding,
            "high0": high0,
            "high1": high1,
            "coordinates": coordinates,
            "labels": labels,
        },
    )
    if not np.isfinite(logits).all() or not np.isfinite(scores).all() or scores[0, 0] < 0.7:
        raise ValueError("Meta couldn't separate that surface confidently. Your reel is unchanged.")
    mask = (
        np.array(Image.fromarray(logits[0, 0]).resize((width, height), Image.Resampling.BILINEAR))
        > 0
    )

    def hits(points):
        pixels = np.round(points.reshape(-1, 2) * [width - 1, height - 1]).astype(int)
        return mask[pixels[:, 1], pixels[:, 0]]

    if not hits(seeds).all() or hits(protected).any():
        raise ValueError("Meta couldn't protect the surrounding surfaces. Your reel is unchanged.")
    return refine_mask(mask, protected)
