from server.audio import DURATIONS, KINDS, SoundLibrary
from server.models import (
    COLORS,
    Cue,
    CueCreate,
    CuePatch,
    EditRequest,
    ObjectCreate,
    ObjectPatch,
    Project,
    ProjectPatch,
    SceneObject,
    snap_time,
)
from server.storage import Conflict, NotFound


class Studio:
    def __init__(self, store, library: SoundLibrary):
        self.store = store
        self.library = library

    def get(self, owner: str, project_id: str, revision: int | None = None) -> Project:
        project = self.store.get(owner, project_id)
        if revision is not None and revision != project.revision:
            raise Conflict("This scene changed in another tab. Reload it before editing.")
        return project

    def commit(self, owner: str, before: Project, after: Project, remember: bool = True):
        after = Project.model_validate(after.model_dump())
        self.library.validate(after)
        return self.store.commit(owner, before, after, remember=remember)

    @staticmethod
    def object(project: Project, object_id: str) -> SceneObject:
        obj = next((obj for obj in project.objects if obj.id == object_id), None)
        if not obj:
            raise NotFound("Select an object in this scene.")
        return obj

    @staticmethod
    def cue(project: Project, cue_id: str) -> Cue:
        cue = next((cue for cue in project.cues if cue.id == cue_id), None)
        if not cue:
            raise NotFound("Select a sound cue in this scene.")
        return cue

    def patch_project(self, owner: str, project_id: str, request: ProjectPatch):
        before = self.get(owner, project_id, request.revision)
        after = before.model_copy(
            update=request.model_dump(exclude={"revision"}, exclude_unset=True)
        )
        return self.commit(owner, before, after)

    def add_object(self, owner: str, project_id: str, request: ObjectCreate):
        before = self.get(owner, project_id, request.revision)
        if len(before.objects) >= 3:
            raise ValueError("This focused studio supports up to three objects per scene.")
        after = before.model_copy(deep=True)
        after.objects.append(
            SceneObject(
                name=request.name,
                profile=request.profile,
                color=COLORS[len(after.objects)],
                keyframes=[request.box],
            )
        )
        return self.commit(owner, before, after)

    def patch_object(self, owner: str, project_id: str, object_id: str, request: ObjectPatch):
        before = self.get(owner, project_id, request.revision)
        after = before.model_copy(deep=True)
        obj = self.object(after, object_id)
        for key in ("name", "gain_db", "muted"):
            if key in request.model_fields_set:
                setattr(obj, key, getattr(request, key))
        if request.keyframe:
            frame = request.keyframe.model_copy(
                update={"time": snap_time(request.keyframe.time, after.media.fps)}
            )
            obj.keyframes = sorted(
                [item for item in obj.keyframes if abs(item.time - frame.time) > 0.001] + [frame],
                key=lambda item: item.time,
            )
        return self.commit(owner, before, after)

    def delete_object(self, owner: str, project_id: str, object_id: str, revision: int):
        before = self.get(owner, project_id, revision)
        self.object(before, object_id)
        after = before.model_copy(deep=True)
        after.objects = [obj for obj in after.objects if obj.id != object_id]
        after.cues = [cue for cue in after.cues if cue.object_id != object_id]
        return self.commit(owner, before, after)

    def add_cue(self, owner: str, project_id: str, request: CueCreate):
        before = self.get(owner, project_id, request.revision)
        obj = self.object(before, request.object_id)
        if len(before.cues) >= 100:
            raise ValueError("A scene supports up to 100 sound cues.")
        time = snap_time(request.time, before.media.fps)
        asset_id = request.asset_id or obj.sound_overrides.get(
            request.kind, f"{obj.profile}-{request.kind}"
        )
        asset = next((item for item in before.assets if item.id == asset_id), None)
        duration = min(
            asset.duration if asset else DURATIONS[request.kind], before.media.duration - time
        )
        if duration < 0.04:
            raise ValueError("Move the playhead at least one frame before the end of the clip.")
        cue = Cue(
            object_id=obj.id,
            kind=request.kind,
            time=time,
            duration=duration,
            asset_id=asset_id,
            gain_db=-12 if request.kind == "ambience" else -4,
        )
        after = before.model_copy(deep=True)
        after.cues.append(cue)
        return self.commit(owner, before, after)

    def patch_cue(self, owner: str, project_id: str, cue_id: str, request: CuePatch):
        before = self.get(owner, project_id, request.revision)
        self.cue(before, cue_id)
        after = before.model_copy(deep=True)
        updates = request.model_dump(exclude={"revision"}, exclude_unset=True)
        if updates.get("time") is not None:
            updates["time"] = snap_time(updates["time"], after.media.fps)
        after.cues = [
            Cue.model_validate({**cue.model_dump(), **updates}) if cue.id == cue_id else cue
            for cue in after.cues
        ]
        return self.commit(owner, before, after)

    def delete_cue(self, owner: str, project_id: str, cue_id: str, revision: int):
        before = self.get(owner, project_id, revision)
        self.cue(before, cue_id)
        after = before.model_copy(deep=True)
        after.cues = [cue for cue in after.cues if cue.id != cue_id]
        return self.commit(owner, before, after)

    def edit(self, owner: str, project_id: str, request: EditRequest):
        before = self.get(owner, project_id, request.revision)
        after = self.apply_edit(before, request)
        return self.commit(owner, before, after)

    def apply_edit(self, before: Project, request: EditRequest) -> Project:
        after = before.model_copy(deep=True)
        obj = self.object(after, request.object_id)
        if request.cue_id and self.cue(after, request.cue_id).object_id != obj.id:
            raise ValueError("The selected cue does not belong to the selected object.")
        for operation in request.operations:
            if operation.cue_ids:
                for cue_id in operation.cue_ids:
                    if self.cue(after, cue_id).object_id != obj.id:
                        raise ValueError("A direction cannot modify another object's sound layer.")
            targets = [
                cue
                for cue in after.cues
                if cue.object_id == request.object_id
                and (request.cue_id is None or cue.id == request.cue_id)
                and (operation.kind is None or cue.kind == operation.kind)
                and (operation.cue_ids is None or cue.id in operation.cue_ids)
            ]
            whole_object = (
                request.cue_id is None and operation.kind is None and operation.cue_ids is None
            )
            if whole_object and operation.type in ("gain", "mute"):
                if operation.value is None:
                    raise ValueError("This edit needs a value.")
                if operation.type == "gain":
                    obj.gain_db = operation.value
                else:
                    obj.muted = bool(operation.value)
                continue
            sound_identity = (
                operation.type == "set_sound"
                and request.cue_id is None
                and operation.cue_ids is None
            )
            if not targets and not sound_identity:
                raise ValueError("There are no matching cues on this object. Add a cue first.")
            if operation.type == "set_sound":
                if not operation.asset_id and not operation.profile:
                    raise ValueError("Choose a material or a recorded sound.")
                if sound_identity:
                    for kind in KINDS:
                        obj.sound_overrides.setdefault(kind, f"{obj.profile}-{kind}")
                    for kind in [operation.kind] if operation.kind else KINDS:
                        obj.sound_overrides[kind] = (
                            operation.asset_id or f"{operation.profile}-{kind}"
                        )
                if operation.profile and sound_identity:
                    obj.profile = operation.profile
                for cue in targets:
                    cue.asset_id = operation.asset_id or f"{operation.profile}-{cue.kind}"
                    if operation.asset_id:
                        asset = next(
                            (item for item in after.assets if item.id == operation.asset_id), None
                        )
                        if asset:
                            cue.duration = min(asset.duration, after.media.duration - cue.time)
            elif operation.type == "shift":
                if operation.frames is None:
                    raise ValueError("Timing edits must specify a number of frames.")
                for cue in targets:
                    cue.time = max(
                        0,
                        min(
                            after.media.duration - cue.duration,
                            snap_time(
                                cue.time + operation.frames / after.media.fps, after.media.fps
                            ),
                        ),
                    )
            else:
                field = {
                    "gain": "gain_db",
                    "pan": "pan",
                    "mute": "muted",
                    "filter": "lowpass_hz",
                }[operation.type]
                if operation.value is None and field not in ("pan", "lowpass_hz"):
                    raise ValueError("This edit needs a value.")
                for cue in targets:
                    setattr(
                        cue, field, bool(operation.value) if field == "muted" else operation.value
                    )
        return after

    def undo(self, owner: str, project_id: str, revision: int):
        before = self.get(owner, project_id, revision)
        if not before.undo_revisions:
            raise ValueError("There is nothing to undo yet.")
        restored = self.store.historical(owner, project_id, before.undo_revisions[-1])
        restored.undo_revisions = before.undo_revisions[:-1]
        return self.commit(owner, before, restored, remember=False)
