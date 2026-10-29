import hashlib
import time
from pathlib import Path

import cv2
import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from server.models import Project, RecolorEffect
from server.segmentation import (
    INPUT_SIZE,
    model_info,
    predict_mask,
    propagate_mask,
    refine_tracked_mask,
    tracking_envelope,
)

cv2.setNumThreads(1)


def preview_path(project: Project, folder: Path) -> Path:
    return (
        folder / "previews" / f"{project.preview_id}.mp4"
        if project.preview_id
        else folder / "source.mp4"
    )


def region_at(effect: RecolorEffect, timestamp: float) -> np.ndarray | None:
    left = effect.keyframes[0]
    for right in effect.keyframes[1:]:
        if timestamp < right.time:
            if not left.visible:
                return None
            factor = max(0, (timestamp - left.time) / (right.time - left.time))
            return np.array(
                [
                    (a.x + (b.x - a.x) * factor, a.y + (b.y - a.y) * factor)
                    for a, b in zip(left.points, right.points, strict=True)
                ],
                dtype=np.float32,
            )
        left = right
    if not left.visible:
        return None
    return np.array([(point.x, point.y) for point in left.points], dtype=np.float32)


def hls_color(value: str) -> np.ndarray:
    rgb = np.array(
        [[[int(value[index : index + 2], 16) / 255 for index in (1, 3, 5)]]], dtype=np.float32
    )
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2HLS)[0, 0]


def color_mask(hls: np.ndarray, source: np.ndarray, strong: bool = False) -> np.ndarray:
    hue, lightness, saturation = cv2.split(hls)
    source_hue, source_lightness, source_saturation = source
    source_chroma = source_saturation * (1 - abs(2 * source_lightness - 1))
    chroma = saturation * (1 - np.abs(2 * lightness - 1))
    if source_saturation >= 0.18 and source_chroma >= 0.08:
        distance = np.abs(hue - source_hue)
        brightness = np.minimum(1, lightness / max(0.05, float(source_lightness)))
        threshold = np.maximum(0.02, source_chroma * brightness * (0.4 if strong else 0.2))
        return (
            (np.minimum(distance, 360 - distance) < (20 if strong else 35))
            & (saturation > (0.12 if strong else 0.08))
            & (chroma > threshold)
        )
    matching = (saturation < 0.3) | (chroma < 0.12)
    if source_lightness > 0.7:
        matching &= lightness > (max(0.36, float(source_lightness) - 0.35) if strong else 0.36)
    elif source_lightness < 0.25:
        matching &= lightness < (min(0.45, float(source_lightness) + 0.15) if strong else 0.45)
    else:
        matching &= np.abs(lightness - source_lightness) < (0.18 if strong else 0.3)
    return matching


def surface_components(
    hls: np.ndarray, gray: np.ndarray, source: np.ndarray, *, split_edges: bool = True
):
    strong = color_mask(hls, source, strong=True).astype(np.uint8)
    if split_edges:
        pale = source[1] > 0.7 and source[2] * (1 - abs(2 * source[1] - 1)) < 0.08
        low, high = (8, 24) if pale else (15, 45)
        edges = cv2.dilate(cv2.Canny(gray, low, high), np.ones((3, 3), np.uint8))
        strong[edges > 0] = 0
    strong = cv2.morphologyEx(strong, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return cv2.connectedComponentsWithStats(strong)


def seeds_at(effect: RecolorEffect, timestamp: float, field: str) -> np.ndarray:
    left = effect.keyframes[0]
    for right in effect.keyframes[1:]:
        if timestamp < right.time:
            a, b = getattr(left, field), getattr(right, field)
            factor = max(0, (timestamp - left.time) / (right.time - left.time))
            if not right.visible or len(a) != len(b):
                points = a if factor < 0.5 or not right.visible else b
                return np.array([(point.x, point.y) for point in points], dtype=np.float32)
            remaining = list(b)
            points = []
            for point in a:
                match = min(
                    remaining, key=lambda other: (point.x - other.x) ** 2 + (point.y - other.y) ** 2
                )
                remaining.remove(match)
                points.append(
                    (point.x + (match.x - point.x) * factor, point.y + (match.y - point.y) * factor)
                )
            return np.array(points, dtype=np.float32)
        left = right
    return np.array([(point.x, point.y) for point in getattr(left, field)], dtype=np.float32)


class RecolorTrack:
    def __init__(self, effect: RecolorEffect):
        self.effect = effect
        self.source = hls_color(effect.source_color)
        self.target = hls_color(effect.color)
        self.grounded = any(frame.seeds for frame in effect.keyframes)
        self.reference_lightness = None
        self.highlight_lightness = None
        self.previous_gray = None
        self.features = None
        self.previous_polygon = None
        self.previous_mask = None
        self.color_models = None
        self.anchor = -1
        self.changed_frames = 0
        self.visible_frames = 0
        self.model_mask = None
        self.model_gray = None
        self.model_anchor = -1
        self.model_timestamp = -1.0

    def _snap_surface(
        self, hls: np.ndarray, polygon: np.ndarray, timestamp: float, gray: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray] | None:
        height, width = hls.shape[:2]
        guide = np.zeros((height, width), dtype=np.uint8)
        cv2.fillPoly(guide, [np.round(polygon).astype(np.int32)], 255)
        if self.grounded:
            _, labels, _, _ = surface_components(
                hls, gray, self.source, split_edges=self.effect.surface_kind == "object"
            )
            chosen = set()
            radius = max(6, round(min(width, height) * 0.035))
            for point in seeds_at(self.effect, timestamp, "seeds"):
                px, py = np.round(point * [width - 1, height - 1]).astype(int)
                left, top = max(0, px - radius), max(0, py - radius)
                region = labels[top : py + radius + 1, left : px + radius + 1]
                rows, columns = np.nonzero(region)
                if len(rows):
                    nearest = np.argmin((columns + left - px) ** 2 + (rows + top - py) ** 2)
                    chosen.add(int(region[rows[nearest], columns[nearest]]))
            if not chosen:
                return None
            selected = np.isin(labels, list(chosen))
            margin = 2
            if self.effect.surface_kind == "fabric":
                margin = max(2, round(min(width, height) * 0.08))
            inside = cv2.dilate(guide, np.ones((2 * margin + 1,) * 2, np.uint8))
            selected &= inside > 0
            excluded = (labels > 0) & ~selected
            protected = np.zeros_like(guide)
            for point in seeds_at(self.effect, timestamp, "protected"):
                px, py = np.round(point * [width - 1, height - 1]).astype(int)
                cv2.circle(protected, (px, py), max(3, radius // 4), 255, -1)
            excluded |= protected > 0
            if not np.any(selected & ~excluded):
                return None
            return selected.astype(np.uint8) * 255, excluded
        area = np.count_nonzero(guide)
        strong = cv2.morphologyEx(
            color_mask(hls, self.source, strong=True).astype(np.uint8),
            cv2.MORPH_OPEN,
            np.ones((3, 3), np.uint8),
        )
        count, labels, stats, centers = cv2.connectedComponentsWithStats(strong)
        center = polygon.mean(axis=0) / [width, height]
        if self.previous_mask is not None:
            moments = cv2.moments(self.previous_mask, binaryImage=True)
            if moments["m00"]:
                center = np.array(
                    [
                        moments["m10"] / moments["m00"] / width,
                        moments["m01"] / moments["m00"] / height,
                    ]
                )
        radius = max(
            0.18,
            min(0.35, float(np.linalg.norm(np.ptp(polygon, axis=0) / [width, height])) * 0.75),
        )
        candidates = [
            index
            for index in range(1, count)
            if max(30, area * 0.04) <= stats[index, cv2.CC_STAT_AREA] <= area * 6
            and np.linalg.norm(centers[index] / [width, height] - center) < radius
        ]
        if not candidates:
            return None
        chosen = min(
            candidates,
            key=lambda index: np.linalg.norm(centers[index] / [width, height] - center),
        )
        selected = labels == chosen
        excluded = (strong > 0) & ~selected
        return selected.astype(np.uint8) * 255, excluded

    def _surface_mask(
        self,
        frame: np.ndarray,
        guide: np.ndarray,
        matching: np.ndarray,
        previous: np.ndarray | None,
        excluded: np.ndarray,
    ) -> np.ndarray | None:
        if self.grounded:
            foreground = (cv2.erode(guide, np.ones((3, 3), np.uint8)) > 0) & matching
        else:
            distance = cv2.distanceTransform(guide, cv2.DIST_L2, 3)
            foreground = (distance > distance.max() * 0.6) & matching
        if previous is not None:
            distance = cv2.distanceTransform(previous, cv2.DIST_L2, 3)
            foreground |= (distance > distance.max() * 0.6) & matching
        if foreground.sum() < 5:
            return None
        source_chroma = self.source[2] * (1 - abs(2 * self.source[1] - 1))
        if self.source[1] > 0.7 and source_chroma < 0.08:
            samples = frame[foreground].astype(np.float32) / 255
            observed = np.median((samples.max(axis=1) + samples.min(axis=1)) / 2)
            if observed < self.source[1] - 0.35:
                return None
        mask = np.full(guide.shape, cv2.GC_PR_BGD, dtype=np.uint8)
        mask[guide > 0] = cv2.GC_PR_FGD
        if previous is not None:
            mask[previous > 0] = cv2.GC_PR_FGD
        mask[foreground] = cv2.GC_FGD
        mask[~matching] = cv2.GC_BGD
        mask[excluded] = cv2.GC_BGD
        height, width = guide.shape
        scale = min(1, 224 / max(height, width))
        size = (max(2, round(width * scale)), max(2, round(height * scale)))
        small = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
        labels = cv2.resize(mask, size, interpolation=cv2.INTER_NEAREST)
        if np.count_nonzero(labels == cv2.GC_FGD) < 5:
            return None
        if not np.any((labels == cv2.GC_BGD) | (labels == cv2.GC_PR_BGD)):
            return (guide > 0) & matching
        initialize = self.color_models is None
        if initialize:
            self.color_models = (
                np.zeros((1, 65), dtype=np.float64),
                np.zeros((1, 65), dtype=np.float64),
            )
        cv2.setRNGSeed(0)
        cv2.grabCut(
            small,
            labels,
            None,
            *self.color_models,
            2 if initialize else 1,
            cv2.GC_INIT_WITH_MASK if initialize else cv2.GC_EVAL,
        )
        selected = cv2.resize(
            ((labels == cv2.GC_FGD) | (labels == cv2.GC_PR_FGD)).astype(np.uint8),
            (width, height),
            interpolation=cv2.INTER_NEAREST,
        )
        count, components = cv2.connectedComponents(selected)
        keep = np.zeros(count, dtype=bool)
        keep[np.unique(components[foreground])] = True
        keep[0] = False
        return (keep[components] | (guide > 0)) & matching & ~excluded

    def apply(
        self,
        frame: np.ndarray,
        gray: np.ndarray,
        timestamp: float,
        source_frame: np.ndarray | None = None,
    ) -> np.ndarray:
        guide = region_at(self.effect, timestamp)
        if guide is None:
            self.features = None
            self.previous_gray = None
            self.previous_mask = None
            self.color_models = None
            self.model_mask = None
            self.model_gray = None
            self.model_anchor = -1
            self.model_timestamp = -1.0
            return frame
        self.visible_frames += 1
        height, width = frame.shape[:2]
        polygon = guide * np.array([width - 1, height - 1], dtype=np.float32)
        anchor = sum(key.time <= timestamp for key in self.effect.keyframes)
        tracking_transform = None
        if (
            anchor == self.anchor
            and self.features is not None
            and self.previous_gray is not None
            and self.previous_polygon is not None
        ):
            moved, status, _ = cv2.calcOpticalFlowPyrLK(
                self.previous_gray, gray, self.features, None, winSize=(21, 21), maxLevel=2
            )
            if moved is not None and status is not None:
                good = status.ravel().astype(bool)
                if good.sum() >= 4:
                    transform, _ = cv2.estimateAffinePartial2D(
                        self.features[good], moved[good], method=cv2.RANSAC, ransacReprojThreshold=2
                    )
                    if transform is not None:
                        scale = float(np.hypot(transform[0, 0], transform[0, 1]))
                        distance = float(np.linalg.norm(transform[:, 2]))
                        if 0.9 <= scale <= 1.1 and distance < min(width, height) * 0.15:
                            tracking_transform = transform
                            tracked = cv2.transform(self.previous_polygon[None], transform)[0]
                            polygon = tracked * 0.85 + polygon * 0.15
        if self.grounded and self.effect.surface_kind == "fabric":
            # Garment motion must not drag an explicitly cropped edge inward.
            for axis, extent in enumerate((width - 1, height - 1)):
                polygon[guide[:, axis] <= 0, axis] = 0
                polygon[guide[:, axis] >= 1, axis] = extent
        polygon[:, 0] = np.clip(polygon[:, 0], 0, width - 1)
        polygon[:, 1] = np.clip(polygon[:, 1], 0, height - 1)
        self.previous_gray, self.previous_polygon, self.anchor = gray, polygon, anchor

        image_hls = cv2.cvtColor(frame.astype(np.float32) / 255, cv2.COLOR_RGB2HLS)
        snapped = self._snap_surface(image_hls, polygon, timestamp, gray)
        if snapped is None:
            self.features = None
            self.previous_mask = None
            self.color_models = None
            return frame
        full_mask, excluded = snapped
        if self.effect.mask_model == "sam2.1-hiera-tiny":
            model_guide = np.where(excluded, 0, full_mask).astype(np.uint8)
            if (
                self.model_mask is None
                or self.model_anchor != anchor
                or timestamp - self.model_timestamp >= 1
            ):
                self.model_mask = predict_mask(
                    source_frame if source_frame is not None else frame,
                    polygon,
                    seeds_at(self.effect, timestamp, "seeds"),
                    seeds_at(self.effect, timestamp, "protected"),
                    model_guide,
                    self.effect.mask_model_sha256,
                )
                self.model_anchor = anchor
                self.model_timestamp = timestamp
            else:
                self.model_mask = propagate_mask(self.model_mask, self.model_gray, gray)
            if self.effect.surface_kind == "fabric":
                # Preserve support for fabric revealed by a moving hand or fold.
                self.model_mask = tracking_envelope(self.model_mask)
            self.model_mask = refine_tracked_mask(
                self.model_mask, model_guide, (model_info() or {}).get("input_size", INPUT_SIZE)
            )
            self.model_gray = gray
            excluded |= self.model_mask == 0
            full_mask = np.where(excluded, 0, full_mask).astype(np.uint8)
            if np.count_nonzero(full_mask) < 30:
                self.features = None
                self.previous_mask = None
                self.color_models = None
                return frame
        x, y, w, h = cv2.boundingRect(full_mask)
        left, top = max(0, x - round(w * 0.35)), max(0, y - round(h * 0.12))
        right, bottom = min(width, x + w + round(w * 0.35)), min(height, y + h + round(h * 0.12))
        x, y, w, h = left, top, right - left, bottom - top
        region = frame[y : y + h, x : x + w]
        hls = image_hls[y : y + h, x : x + w]
        lightness = hls[:, :, 1]
        matching = color_mask(hls, self.source)
        seed = full_mask[y : y + h, x : x + w]
        if (matching & (seed > 0)).sum() < max(30, np.count_nonzero(seed) * 0.08):
            self.features = None
            self.previous_mask = None
            self.color_models = None
            return frame
        previous = None
        if tracking_transform is not None and self.previous_mask is not None:
            previous = cv2.warpAffine(
                self.previous_mask,
                tracking_transform,
                (width, height),
                flags=cv2.INTER_NEAREST,
            )[y : y + h, x : x + w]
        selected = self._surface_mask(
            region, seed, matching, previous, excluded[y : y + h, x : x + w]
        )
        if selected is None or selected.sum() < 30:
            self.features = None
            self.previous_mask = None
            self.color_models = None
            return frame
        self.previous_mask = np.zeros_like(full_mask)
        self.previous_mask[y : y + h, x : x + w] = selected.astype(np.uint8) * 255
        self.features = cv2.goodFeaturesToTrack(gray, 35, 0.01, 5, mask=self.previous_mask)
        if self.reference_lightness is None:
            self.reference_lightness = float(np.median(lightness[selected]))
            self.highlight_lightness = max(
                self.reference_lightness + 0.08, float(np.quantile(lightness[selected], 0.95))
            )
        matte = cv2.GaussianBlur(selected.astype(np.float32), (5, 5), 0.8)
        matte[selected] = 1
        matte *= matching & ~excluded[y : y + h, x : x + w]
        highlight = np.clip(
            (lightness - self.highlight_lightness) / max(0.05, 1 - self.highlight_lightness),
            0,
            1,
        )
        edited = hls.copy()
        edited[:, :, 0] = self.target[0]
        shaded = self.target[1] * lightness / max(0.05, self.reference_lightness)
        edited[:, :, 1] = np.clip(
            shaded + highlight * (1 - shaded),
            0.015,
            0.985,
        )
        edited[:, :, 2] = self.target[2] * (1 - highlight)
        rgb = cv2.cvtColor(edited, cv2.COLOR_HLS2RGB) * 255
        output = frame.copy()
        output[y : y + h, x : x + w] = np.clip(
            region * (1 - matte[:, :, None]) + rgb * matte[:, :, None], 0, 255
        ).astype(np.uint8)
        self.changed_frames += 1
        return output


def caption_layer(text: str, width: int, height: int) -> np.ndarray:
    layer = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(layer)
    maximum_width = width * 0.84
    font_size = max(14, min(round(height * 0.06), round(width * 0.09)))
    while True:
        font = ImageFont.load_default(size=font_size)
        lines = [""]
        tokens = []
        for word in text.split():
            token = ""
            for character in word:
                if token and draw.textlength(token + character, font=font) > maximum_width:
                    tokens.append(token)
                    token = ""
                token += character
            tokens.append(token)
        for word in tokens:
            trial = f"{lines[-1]} {word}".strip()
            if lines[-1] and draw.textlength(trial, font=font) > maximum_width:
                lines.append(word)
            else:
                lines[-1] = trial
        if font_size <= 14 or (
            len(lines) <= 3
            and all(draw.textlength(line, font=font) <= maximum_width for line in lines)
        ):
            break
        font_size -= 2
    start = round(height * 0.62)
    for row in range(start, height):
        opacity = round(140 * ((row - start) / max(1, height - start)) ** 1.3)
        draw.line((0, row, width, row), fill=(0, 0, 0, opacity))
    draw.multiline_text(
        (width / 2, height * 0.79),
        "\n".join(lines),
        font=font,
        fill=(255, 249, 235),
        stroke_width=max(1, font_size // 32),
        stroke_fill=(0, 0, 0, 130),
        anchor="mm",
        align="center",
        spacing=round(font_size * 0.16),
    )
    return np.array(layer, dtype=np.float32)


def prepare_preview(project: Project, folder: Path) -> Path:
    if not project.visual_edits and project.caption is None:
        project.preview_id = None
        return folder / "source.mp4"
    document = "[" + ",".join(effect.model_dump_json() for effect in project.visual_edits) + "]"
    caption = project.caption.model_dump_json() if project.caption else "null"
    fingerprint = hashlib.sha256(f"surface-v18:{document}:{caption}".encode()).hexdigest()[:24]
    target = folder / "previews" / f"{fingerprint}.mp4"
    if target.is_file():
        project.preview_id = fingerprint
        return target
    target.parent.mkdir(exist_ok=True)
    temporary = target.with_suffix(".partial.mp4")
    reader = imageio_ffmpeg.read_frames(
        str(folder / "source.mp4"),
        pix_fmt="rgb24",
        input_params=["-protocol_whitelist", "file,pipe", "-threads", "1"],
    )
    writer = None
    tracks = [RecolorTrack(effect) for effect in project.visual_edits]
    first_frame = None
    uses_meta = any(effect.mask_model == "sam2.1-hiera-tiny" for effect in project.visual_edits)
    deadline = time.monotonic() + (300 if uses_meta else 120)
    try:
        metadata = next(reader)
        width, height = metadata["size"]
        if max(width, height) > 1280:
            raise ValueError("Upload this clip as a video first so it can be resized for editing.")
        title = caption_layer(project.caption.text, width, height) if project.caption else None
        writer = imageio_ffmpeg.write_frames(
            str(temporary),
            (width, height),
            fps=project.media.fps,
            codec="libx264",
            pix_fmt_in="rgb24",
            pix_fmt_out="yuv420p",
            macro_block_size=1,
            ffmpeg_log_level="error",
            output_params=[
                "-crf",
                "20",
                "-preset",
                "veryfast",
                "-threads",
                "1",
                "-movflags",
                "+faststart",
            ],
        )
        writer.send(None)
        for index, values in enumerate(reader):
            if time.monotonic() > deadline:
                raise ValueError("This color edit took too long. Try a shorter clip.")
            frame = np.frombuffer(values, dtype=np.uint8).reshape(height, width, 3)
            source_frame = frame
            gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
            for track in tracks:
                frame = track.apply(
                    frame, gray, index / project.media.fps, source_frame=source_frame
                )
            if title is not None:
                alpha = title[:, :, 3:4] / 255
                frame = np.clip(frame * (1 - alpha) + title[:, :, :3] * alpha, 0, 255).astype(
                    np.uint8
                )
            if first_frame is None:
                first_frame = frame.copy()
            writer.send(frame.tobytes())
        writer.close()
        writer = None
        if any(
            track.changed_frames < 2 or track.changed_frames < track.visible_frames * 0.9
            for track in tracks
        ):
            raise ValueError(
                "I couldn't isolate that color reliably. Try a clearer item or a different shot."
            )
        if not temporary.is_file() or temporary.stat().st_size < 100:
            raise ValueError("The color edit could not be rendered. Your reel is unchanged.")
        temporary.replace(target)
        if first_frame is not None:
            poster = Image.fromarray(first_frame)
            poster.thumbnail((640, 1280))
            poster.save(target.with_suffix(".jpg"), quality=88)
        project.preview_id = fingerprint
        return target
    finally:
        reader.close()
        if writer is not None:
            writer.close()
        temporary.unlink(missing_ok=True)
