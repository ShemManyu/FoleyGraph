import math
import re
import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ActionKind = Literal["footstep", "impact", "movement", "ambience"]
Profile = Literal["wood", "metal", "stone", "soft", "glass", "paper", "water", "synth"]
COLORS = ("#eab66b", "#72c9b0", "#a89aee")
IDENTIFIER = re.compile(r"^[a-zA-Z0-9_-]{1,80}$")


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> str:
    return datetime.now(UTC).isoformat()


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Box(Model):
    time: float = Field(ge=0, le=20)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)
    visible: bool = True

    @model_validator(mode="after")
    def inside_frame(self):
        if self.x + self.width > 1.00001 or self.y + self.height > 1.00001:
            raise ValueError("The selection must stay inside the video frame.")
        return self


class SceneObject(Model):
    id: str = Field(default_factory=new_id, pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    name: str = Field(min_length=1, max_length=60)
    color: str = Field(default=COLORS[0], pattern=r"^#[0-9a-fA-F]{6}$")
    profile: Profile = "wood"
    sound_overrides: dict[ActionKind, str] = Field(default_factory=dict, max_length=4)
    gain_db: float = Field(default=0, ge=-36, le=12)
    muted: bool = False
    keyframes: list[Box] = Field(default_factory=list, max_length=80)


class Cue(Model):
    id: str = Field(default_factory=new_id, pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    object_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    kind: ActionKind = "footstep"
    time: float = Field(ge=0, le=20)
    duration: float = Field(default=0.3, ge=0.04, le=20)
    asset_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    gain_db: float = Field(default=0, ge=-36, le=12)
    pan: float | None = Field(default=None, ge=-1, le=1)
    playback_rate: float = Field(default=1, ge=0.25, le=3)
    lowpass_hz: float | None = Field(default=None, ge=200, le=20000)
    fade_in: float = Field(default=0.005, ge=0, le=2)
    fade_out: float = Field(default=0.025, ge=0, le=2)
    muted: bool = False


class Asset(Model):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    name: str = Field(min_length=1, max_length=100)
    duration: float = Field(gt=0, le=5.1)
    source: str = "Creator recording"


class Media(Model):
    duration: float = Field(gt=0, le=20.05)
    fps: float = Field(gt=0, le=60.01)
    width: int = Field(gt=0, le=4096)
    height: int = Field(gt=0, le=4096)
    filename: str = Field(max_length=150)
    has_audio: bool = False


class Point(Model):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class ColorRegion(Model):
    time: float = Field(ge=0, le=20)
    points: list[Point] = Field(min_length=8, max_length=8)
    seeds: list[Point] = Field(default_factory=list, max_length=12)
    protected: list[Point] = Field(default_factory=list, max_length=24)
    visible: bool = True


class ColorSelection(Model):
    source_color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    surface_kind: Literal["fabric", "object"] = "object"
    keyframes: list[ColorRegion] = Field(min_length=2, max_length=12)
    confidence: float = Field(ge=0, le=1)


class RecolorEffect(ColorSelection):
    id: str = Field(default_factory=new_id, pattern=r"^[a-f0-9]{32}$")
    target: str = Field(min_length=1, max_length=120)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    mask_model: Literal["opencv", "sam2.1-hiera-tiny"] = "opencv"
    mask_model_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def model_provenance(self):
        if (self.mask_model == "opencv") != (self.mask_model_sha256 is None):
            raise ValueError("A Meta surface edit must identify the exact mask model.")
        return self


class MusicBed(Model):
    style: Literal["ambient"] = "ambient"
    gain_db: float = Field(default=-14, ge=-36, le=0)


class ReelCaption(Model):
    text: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def visible_text(self):
        if not self.text.strip():
            raise ValueError("A title needs visible text.")
        return self


class Project(Model):
    schema_version: Literal[1] = 1
    id: str = Field(default_factory=new_id, pattern=r"^[a-f0-9]{32}$")
    name: str = Field(default="Untitled scene", min_length=1, max_length=100)
    brief: str = Field(
        default="A polished social reel with natural, carefully layered sound.", max_length=1200
    )
    media: Media
    objects: list[SceneObject] = Field(default_factory=list, max_length=3)
    cues: list[Cue] = Field(default_factory=list, max_length=100)
    assets: list[Asset] = Field(default_factory=list, max_length=16)
    visual_edits: list[RecolorEffect] = Field(default_factory=list, max_length=6)
    preview_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{24}$")
    music: MusicBed | None = None
    caption: ReelCaption | None = None
    source_audio_muted: bool = False
    source_credit: str = Field(default="", max_length=1000)
    revision: int = 0
    undo_revisions: list[int] = Field(default_factory=list, max_length=20)
    created_at: str = Field(default_factory=now)
    updated_at: str = Field(default_factory=now)
    analysis_note: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def valid_graph(self):
        object_ids = {obj.id for obj in self.objects}
        if len(object_ids) != len(self.objects):
            raise ValueError("Object IDs must be unique.")
        if len({cue.id for cue in self.cues}) != len(self.cues):
            raise ValueError("Cue IDs must be unique.")
        if len({asset.id for asset in self.assets}) != len(self.assets):
            raise ValueError("Asset IDs must be unique.")
        for obj in self.objects:
            times = [box.time for box in obj.keyframes]
            if times != sorted(set(times)) or any(t > self.media.duration for t in times):
                raise ValueError(
                    "Tracking keyframes must have unique, ordered times inside the clip."
                )
        for cue in self.cues:
            if cue.object_id not in object_ids:
                raise ValueError("Every cue must belong to a scene object.")
            if cue.time + cue.duration > self.media.duration + 0.001:
                raise ValueError("A cue cannot extend beyond the clip.")
        if len({effect.id for effect in self.visual_edits}) != len(self.visual_edits):
            raise ValueError("Visual edit IDs must be unique.")
        for effect in self.visual_edits:
            times = [frame.time for frame in effect.keyframes]
            if times != sorted(set(times)) or any(t > self.media.duration for t in times):
                raise ValueError("Color selections need ordered keyframes inside the clip.")
        return self


class Versioned(Model):
    revision: int = Field(ge=0)


class ProjectPatch(Versioned):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    brief: str | None = Field(default=None, max_length=1200)


class ObjectCreate(Versioned):
    name: str = Field(min_length=1, max_length=60)
    box: Box
    profile: Profile = "wood"


class ObjectPatch(Versioned):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    gain_db: float | None = Field(default=None, ge=-36, le=12)
    muted: bool | None = None
    keyframe: Box | None = None


class CueCreate(Versioned):
    object_id: str
    kind: ActionKind
    time: float = Field(ge=0, le=20)
    asset_id: str | None = None


class CuePatch(Versioned):
    time: float | None = Field(default=None, ge=0, le=20)
    duration: float | None = Field(default=None, ge=0.04, le=20)
    gain_db: float | None = Field(default=None, ge=-36, le=12)
    pan: float | None = Field(default=None, ge=-1, le=1)
    playback_rate: float | None = Field(default=None, ge=0.25, le=3)
    lowpass_hz: float | None = Field(default=None, ge=200, le=20000)
    fade_in: float | None = Field(default=None, ge=0, le=2)
    fade_out: float | None = Field(default=None, ge=0, le=2)
    muted: bool | None = None


class Operation(Model):
    type: Literal["set_sound", "gain", "pan", "shift", "mute", "filter"]
    kind: ActionKind | None = None
    cue_ids: list[str] | None = Field(default=None, max_length=100)
    profile: Profile | None = None
    asset_id: str | None = None
    value: float | None = None
    frames: int | None = Field(default=None, ge=-1200, le=1200)


class EditRequest(Versioned):
    object_id: str
    cue_id: str | None = None
    operations: list[Operation] = Field(min_length=1, max_length=8)


class CommandRequest(Versioned):
    object_id: str
    cue_id: str | None = None
    instruction: str = Field(min_length=1, max_length=1200)


class AnalyzeRequest(Versioned):
    brief: str = Field(min_length=1, max_length=1200)


class Direction(Model):
    message: str = Field(max_length=300)
    operations: list[Operation] = Field(default_factory=list, max_length=8)


class ChatTurn(Model):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=2000)


class SceneDirectionRequest(Versioned):
    instruction: str = Field(min_length=1, max_length=1200)
    history: list[ChatTurn] = Field(default_factory=list, max_length=12)
    object_id: str | None = None
    cue_id: str | None = None


class SoundAction(Model):
    type: Literal["sound"]
    object_id: str
    cue_id: str | None = None
    operations: list[Operation] = Field(min_length=1, max_length=8)


class RecolorAction(Model):
    type: Literal["recolor"]
    target: str = Field(
        min_length=1, max_length=120, description="The visible physical surface to change."
    )
    color: str = Field(
        pattern=r"^#[0-9a-fA-F]{6}$",
        description="A destination color chosen by the user, not an assistant suggestion.",
    )
    effect_id: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{32}$",
        description="An existing visual_edits.id, or null for a new selection. Never an object ID.",
    )


class MusicAction(Model):
    type: Literal["music"]
    enabled: bool = True
    gain_db: float | None = Field(default=None, ge=-36, le=0)
    replace_original: bool = False


class CaptionAction(Model):
    type: Literal["caption"]
    text: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
        description=(
            "The full-clip on-video title, or null to remove it. Preserve explicitly quoted wording. "
            "No timing or layout input is needed or supported."
        ),
    )


class OriginalAudioAction(Model):
    type: Literal["original_audio"]
    muted: bool


class SoundPassAction(Model):
    type: Literal["sound_pass"]
    brief: str = Field(min_length=1, max_length=1200)


class UndoAction(Model):
    type: Literal["undo"]


class SceneDirection(Model):
    message: str = Field(
        min_length=1,
        max_length=300,
        description="A short question if information is missing; otherwise what changed.",
    )
    actions: list[
        Annotated[
            SoundAction
            | RecolorAction
            | MusicAction
            | CaptionAction
            | OriginalAudioAction
            | SoundPassAction
            | UndoAction,
            Field(discriminator="type"),
        ]
    ] = Field(
        default_factory=list,
        max_length=4,
        description="Use [] for questions or incomplete instructions. Never guess a missing color.",
    )

    @model_validator(mode="after")
    def unambiguous_actions(self):
        types = [action.type for action in self.actions]
        if any(types.count(kind) > 1 for kind in ("recolor", "music", "caption")):
            raise ValueError("Change one visible item, music bed, and title at a time.")
        if "undo" in types and len(types) != 1:
            raise ValueError("Undo must be a separate edit.")
        return self


def box_at(obj: SceneObject, time: float) -> Box | None:
    frames = obj.keyframes
    if not frames:
        return None
    left = frames[0]
    for right in frames[1:]:
        if time < right.time:
            if not left.visible:
                return left
            factor = max(0, min(1, (time - left.time) / max(0.001, right.time - left.time)))
            values = {
                key: getattr(left, key) + (getattr(right, key) - getattr(left, key)) * factor
                for key in ("x", "y", "width", "height")
            }
            return Box(time=time, visible=left.visible, **values)
        left = right
    return left


def snap_time(time: float, fps: float) -> float:
    return math.floor(time * fps + 0.5) / fps


Revision = Annotated[int, Field(ge=0)]
