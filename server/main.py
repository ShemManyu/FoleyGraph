import hashlib
import logging
import re
import secrets
import shutil
import tempfile
import threading
import time
import zipfile
from collections import defaultdict, deque
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from azure.core.exceptions import AzureError
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, URLSafeTimedSerializer
from openai import OpenAIError, RateLimitError
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from server.audio import PROFILES, SoundLibrary
from server.config import Settings, source_revision
from server.demo import copy_demo_sounds, demo_project, make_demo_video
from server.director import Director, DirectorUnavailable
from server.media import (
    import_bundle,
    normalize_audio,
    normalize_video,
    render_export,
    run_ffmpeg,
)
from server.models import (
    AnalyzeRequest,
    Asset,
    CommandRequest,
    CueCreate,
    CuePatch,
    EditRequest,
    MusicBed,
    ObjectCreate,
    ObjectPatch,
    Project,
    ProjectPatch,
    RecolorEffect,
    ReelCaption,
    SceneDirectionRequest,
    Versioned,
    new_id,
    now,
)
from server.segmentation import model_info as mask_model_info
from server.storage import AzureStore, Conflict, LocalStore, NotFound
from server.studio import Studio
from server.visual import prepare_preview, preview_path

logger = logging.getLogger("foleygraph")


class RateLimiter:
    def __init__(self):
        self.buckets = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: tuple, limit: int) -> bool:
        timestamp = time.monotonic()
        with self.lock:
            if len(self.buckets) > 4000:
                self.buckets = defaultdict(
                    deque,
                    {
                        key: values
                        for key, values in self.buckets.items()
                        if values and values[-1] > timestamp - 60
                    },
                )
            bucket = self.buckets[key]
            while bucket and bucket[0] < timestamp - 60:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(timestamp)
        return True


def create_app(settings: Settings | None = None, store=None, director=None) -> FastAPI:
    settings = settings or Settings()
    settings.prepare()
    library = SoundLibrary(settings.data_dir)
    library.prepare()
    store = store or (
        AzureStore(settings.storage_account, settings.storage_table)
        if settings.storage_account
        else LocalStore(settings.data_dir / "projects.sqlite3")
    )
    director = director or Director(settings)
    studio = Studio(store, library)
    signer = URLSafeTimedSerializer(settings.workspace_secret, salt="foleygraph-workspace-v1")
    rate = RateLimiter()
    heavy_lock = threading.BoundedSemaphore(1)
    # Freeze this worker's identity before a deployment can replace files on disk.
    backend_revision = source_revision()

    @asynccontextmanager
    async def lifespan(_app):
        await run_in_threadpool(store.check)
        yield

    app = FastAPI(
        title="FoleyGraph", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None
    )
    app.state.settings = settings
    app.state.studio = studio
    app.state.director = director

    @contextmanager
    def media_slot():
        if not heavy_lock.acquire(blocking=False):
            raise HTTPException(
                429, "The studio is processing another clip. Try again in a moment."
            )
        try:
            yield
        finally:
            heavy_lock.release()

    def owner(request: Request) -> str:
        return request.state.owner

    def folder(project: Project) -> Path:
        return settings.data_dir / "media" / project.id

    def can_create(workspace: str):
        if len(store.list(workspace)) >= 20:
            raise ValueError(
                "This workspace holds 20 scenes. Export a backup and delete an old scene first."
            )

    def poster(project: Project):
        run_ffmpeg(
            [
                "-protocol_whitelist",
                "file,pipe",
                "-i",
                str(folder(project) / "source.mp4"),
                "-frames:v",
                "1",
                "-vf",
                "scale=640:-2",
                "-threads",
                "2",
                str(folder(project) / "poster.jpg"),
            ]
        )

    @asynccontextmanager
    async def uploaded(file: UploadFile):
        handle = tempfile.NamedTemporaryFile(dir=settings.data_dir / "temporary", delete=False)
        path = Path(handle.name)
        try:
            total = 0
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > settings.max_upload_bytes:
                    raise HTTPException(413, "Files must be 100 MB or smaller.")
                handle.write(chunk)
            handle.close()
            if total == 0:
                raise ValueError("The uploaded file is empty.")
            yield path
        finally:
            handle.close()
            path.unlink(missing_ok=True)
            await file.close()

    @app.middleware("http")
    async def workspace_and_headers(request: Request, call_next):
        api = request.url.path.startswith("/api/")
        new_cookie = False
        if api:
            signed = request.cookies.get("fg_workspace", "")
            try:
                token = signer.loads(signed, max_age=365 * 24 * 3600)
                if not isinstance(token, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{40,64}", token):
                    raise BadSignature("Invalid workspace.")
            except BadSignature:
                token = secrets.token_urlsafe(32)
                new_cookie = True
            request.state.owner = hashlib.sha256(token.encode()).hexdigest()
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                origin = request.headers.get("origin")
                if origin:
                    parsed = urlsplit(origin)
                    if (
                        parsed.scheme not in ("http", "https")
                        or parsed.netloc.lower() != request.headers.get("host", "").lower()
                    ):
                        return JSONResponse(
                            {"detail": "Cross-origin editing is not allowed."}, status_code=403
                        )
                length = request.headers.get("content-length", "0")
                if not length.isdigit() or int(length) > settings.max_upload_bytes + 1024 * 1024:
                    return JSONResponse(
                        {"detail": "Files must be 100 MB or smaller."}, status_code=413
                    )
                ip = request.client.host if request.client else "unknown"
                if not rate.allow((ip, "writes"), 180):
                    return JSONResponse(
                        {"detail": "Too many edits. Please wait a minute."}, status_code=429
                    )
                if any(
                    request.url.path.endswith(suffix)
                    for suffix in (
                        "/analyze",
                        "/command",
                        "/direct",
                        "/exports",
                        "/transcribe",
                        "/demo",
                    )
                ):
                    if not rate.allow((ip, "processing"), 15):
                        return JSONResponse(
                            {"detail": "Processing limit reached. Please wait a minute."},
                            status_code=429,
                        )
        response = await call_next(request)
        if new_cookie:
            response.set_cookie(
                "fg_workspace",
                signer.dumps(token),
                max_age=365 * 24 * 3600,
                httponly=True,
                secure=request.url.scheme == "https",
                samesite="lax",
            )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(self), geolocation=(), web-share=(self)"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; "
            "font-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        )
        if api and not request.url.path.startswith("/api/samples/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(NotFound)
    async def not_found(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(Conflict)
    async def conflict(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ValueError)
    async def bad_value(_request, exc):
        message = str(exc)
        if isinstance(exc, ValidationError):
            errors = exc.errors(include_url=False, include_input=False)
            message = errors[0]["msg"] if errors else "This edit is not valid."
        return JSONResponse({"detail": message[:400]}, status_code=422)

    @app.exception_handler(zipfile.BadZipFile)
    async def bad_zip(_request, _exc):
        return JSONResponse({"detail": "Choose a valid FoleyGraph project ZIP."}, status_code=422)

    @app.exception_handler(DirectorUnavailable)
    async def director_unavailable(_request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.exception_handler(OpenAIError)
    async def model_error(_request, exc):
        logger.warning("Foundry request failed: %s", type(exc).__name__)
        if isinstance(exc, RateLimitError):
            return JSONResponse(
                {
                    "detail": "The editor is busy. Please try again in a minute. Your reel is unchanged."
                },
                status_code=429,
                headers={"Retry-After": "60"},
            )
        return JSONResponse(
            {
                "detail": "Foundry could not complete this request. Try again shortly; manual editing still works."
            },
            status_code=503,
        )

    @app.exception_handler(AzureError)
    async def storage_error(_request, exc):
        logger.warning("Azure storage request failed: %s", type(exc).__name__)
        return JSONResponse(
            {"detail": "Project storage is temporarily unavailable. Please retry."}, status_code=503
        )

    @app.get("/healthz")
    def health():
        try:
            store.check()
        except Exception:
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return {
            "status": "ok",
            "storage": store.kind,
            "ai_configured": director.configured,
            "version": "1.0.0",
            "backend_revision": backend_revision,
        }

    @app.get("/api/config")
    def configuration():
        return {
            "ai_available": director.configured,
            "voice_available": director.configured and bool(settings.transcription_model),
            "storage": store.kind,
            "mask_model": mask_model_info(),
            "profiles": [{"id": key, "name": label} for key, label in PROFILES.items()],
            "limits": {
                "duration": settings.max_duration,
                "upload_mb": 100,
                "objects": 3,
                "cues": 100,
            },
        }

    @app.get("/api/samples")
    def samples():
        return [{**item, "url": f"/api/samples/{item['id']}.wav"} for item in library.catalog]

    @app.get("/api/samples/{asset_id}.wav")
    def sample(asset_id: str):
        if asset_id not in library.ids:
            raise NotFound("Sample not found.")
        return FileResponse(
            library.samples_dir / f"{asset_id}.wav",
            media_type="audio/wav",
            headers={"Cache-Control": "public, max-age=604800, immutable"},
        )

    @app.get("/api/projects")
    def projects(request: Request):
        return [
            {
                "id": item.id,
                "name": item.name,
                "updated_at": item.updated_at,
                "duration": item.media.duration,
                "objects": len(item.objects),
                "cues": len(item.cues),
            }
            for item in store.list(owner(request))
        ]

    @app.post("/api/projects", status_code=201)
    async def upload_project(request: Request, file: UploadFile = File()):
        workspace = owner(request)
        filename = Path(file.filename or "scene.mp4").name
        await run_in_threadpool(can_create, workspace)
        with media_slot():
            async with uploaded(file) as source:
                project_id = new_id()
                target = settings.data_dir / "media" / project_id
                try:
                    metadata = await run_in_threadpool(
                        normalize_video, source, target / "source.mp4", filename
                    )
                    project = Project(
                        id=project_id,
                        name=Path(filename).stem[:100] or "Untitled scene",
                        media=metadata,
                    )
                    await run_in_threadpool(poster, project)
                    return await run_in_threadpool(store.create, workspace, project)
                except Exception:
                    if target.exists():
                        shutil.rmtree(target)
                    raise

    @app.post("/api/demo", status_code=201)
    def create_demo(request: Request, scene: Literal["coffee", "style"] = "coffee"):
        workspace = owner(request)
        can_create(workspace)
        with media_slot():
            source = settings.data_dir / f"demo-{scene}-v2.mp4"
            make_demo_video(source, scene)
            project = demo_project(source, scene)
            target = folder(project)
            target.mkdir(parents=True)
            shutil.copyfile(source, target / "source.mp4")
            copy_demo_sounds(target, scene)
            prepare_preview(project, target)
            poster(project)
            return store.create(workspace, project)

    @app.post("/api/projects/import", status_code=201)
    async def restore_project(request: Request, file: UploadFile = File()):
        workspace = owner(request)
        await run_in_threadpool(can_create, workspace)
        with media_slot():
            async with uploaded(file) as source:
                project = await run_in_threadpool(import_bundle, source, settings.data_dir, library)
                project.created_at = project.updated_at = now()
                await run_in_threadpool(prepare_preview, project, folder(project))
                await run_in_threadpool(poster, project)
                return await run_in_threadpool(store.create, workspace, project)

    @app.get("/api/projects/{project_id}")
    def project_get(request: Request, project_id: str):
        return studio.get(owner(request), project_id)

    @app.patch("/api/projects/{project_id}")
    def project_patch(request: Request, project_id: str, body: ProjectPatch):
        return studio.patch_project(owner(request), project_id, body)

    @app.delete("/api/projects/{project_id}")
    def project_delete(request: Request, project_id: str, body: Versioned):
        project = studio.get(owner(request), project_id, body.revision)
        store.delete(owner(request), project_id)
        if folder(project).exists():
            shutil.rmtree(folder(project))
        return {"deleted": True}

    @app.get("/api/projects/{project_id}/source.mp4")
    def project_video(request: Request, project_id: str):
        project = studio.get(owner(request), project_id)
        return FileResponse(folder(project) / "source.mp4", media_type="video/mp4")

    @app.get("/api/projects/{project_id}/previews/{preview_id}.mp4")
    def project_preview(request: Request, project_id: str, preview_id: str):
        project = studio.get(owner(request), project_id)
        if not re.fullmatch(r"[a-f0-9]{24}", preview_id):
            raise NotFound("Preview not found.")
        path = folder(project) / "previews" / f"{preview_id}.mp4"
        if not path.is_file():
            raise NotFound("This preview is unavailable. Reopen the reel to render it again.")
        return FileResponse(path, media_type="video/mp4")

    @app.get("/api/projects/{project_id}/poster.jpg")
    def project_poster(request: Request, project_id: str):
        project = studio.get(owner(request), project_id)
        if project.preview_id:
            path = preview_path(project, folder(project)).with_suffix(".jpg")
            if path.is_file():
                return FileResponse(path, media_type="image/jpeg")
        return FileResponse(folder(project) / "poster.jpg", media_type="image/jpeg")

    @app.get("/api/projects/{project_id}/music.wav")
    def project_music(request: Request, project_id: str):
        project = studio.get(owner(request), project_id)
        if not project.music:
            raise NotFound("This reel has no music bed.")
        return FileResponse(library.music_path(project), media_type="audio/wav")

    @app.get("/api/projects/{project_id}/original.wav")
    def project_original_audio(request: Request, project_id: str):
        project = studio.get(owner(request), project_id)
        if not project.media.has_audio:
            raise NotFound("This reel has no original soundtrack.")
        return FileResponse(folder(project) / "source-audio.wav", media_type="audio/wav")

    @app.post("/api/projects/{project_id}/objects")
    def object_add(request: Request, project_id: str, body: ObjectCreate):
        return studio.add_object(owner(request), project_id, body)

    @app.patch("/api/projects/{project_id}/objects/{object_id}")
    def object_patch(request: Request, project_id: str, object_id: str, body: ObjectPatch):
        return studio.patch_object(owner(request), project_id, object_id, body)

    @app.delete("/api/projects/{project_id}/objects/{object_id}")
    def object_delete(request: Request, project_id: str, object_id: str, body: Versioned):
        return studio.delete_object(owner(request), project_id, object_id, body.revision)

    @app.post("/api/projects/{project_id}/cues")
    def cue_add(request: Request, project_id: str, body: CueCreate):
        return studio.add_cue(owner(request), project_id, body)

    @app.patch("/api/projects/{project_id}/cues/{cue_id}")
    def cue_patch(request: Request, project_id: str, cue_id: str, body: CuePatch):
        return studio.patch_cue(owner(request), project_id, cue_id, body)

    @app.delete("/api/projects/{project_id}/cues/{cue_id}")
    def cue_delete(request: Request, project_id: str, cue_id: str, body: Versioned):
        return studio.delete_cue(owner(request), project_id, cue_id, body.revision)

    @app.post("/api/projects/{project_id}/edit")
    def edit(request: Request, project_id: str, body: EditRequest):
        return studio.edit(owner(request), project_id, body)

    @app.post("/api/projects/{project_id}/undo")
    def undo(request: Request, project_id: str, body: Versioned):
        return studio.undo(owner(request), project_id, body.revision)

    @app.post("/api/projects/{project_id}/analyze")
    def analyze(request: Request, project_id: str, body: AnalyzeRequest):
        before = studio.get(owner(request), project_id, body.revision)
        if not director.configured:
            raise DirectorUnavailable(
                "Foundry is not configured. Bind objects and add cues manually."
            )
        with media_slot():
            after = director.analyze(before, preview_path(before, folder(before)), body.brief)
            return studio.commit(owner(request), before, after)

    @app.post("/api/projects/{project_id}/direct")
    def direct_scene(request: Request, project_id: str, body: SceneDirectionRequest):
        workspace = owner(request)
        before = studio.get(workspace, project_id, body.revision)
        if body.object_id:
            studio.object(before, body.object_id)
        if body.cue_id and (
            not body.object_id or studio.cue(before, body.cue_id).object_id != body.object_id
        ):
            raise ValueError("Select an action on the selected object.")
        with media_slot():
            path = preview_path(before, folder(before))
            direction = director.scene_direction(before, path, body)
            if not direction.actions:
                return {"project": before, "message": direction.message}
            if direction.actions[0].type == "undo":
                return {
                    "project": studio.undo(workspace, project_id, before.revision),
                    "message": "Done. Your last change is undone.",
                }
            after = before.model_copy(deep=True)
            for action in direction.actions:
                if action.type == "sound":
                    if body.object_id and action.object_id != body.object_id:
                        raise ValueError("That edit must stay on the explicitly selected layer.")
                    if body.cue_id and action.cue_id != body.cue_id:
                        raise ValueError("That edit must stay on the explicitly selected action.")
                    after = studio.apply_edit(
                        after,
                        EditRequest(
                            revision=before.revision,
                            object_id=action.object_id,
                            cue_id=action.cue_id,
                            operations=action.operations,
                        ),
                    )
                elif action.type == "music":
                    if action.enabled:
                        after.music = MusicBed(
                            gain_db=action.gain_db
                            if action.gain_db is not None
                            else (after.music.gain_db if after.music else -14)
                        )
                        if action.replace_original:
                            after.source_audio_muted = True
                    else:
                        after.music = None
                elif action.type == "original_audio":
                    if not after.media.has_audio:
                        raise ValueError("This clip has no original soundtrack.")
                    after.source_audio_muted = action.muted
                elif action.type == "caption":
                    if action.text is None and after.caption is None:
                        raise ValueError(
                            "There is no editable title to remove. Text already embedded in "
                            "the original footage cannot be erased here."
                        )
                    after.caption = ReelCaption(text=action.text) if action.text else None
                elif action.type == "recolor":
                    if action.effect_id:
                        effect = next(
                            (
                                effect
                                for effect in after.visual_edits
                                if effect.id == action.effect_id
                            ),
                            None,
                        )
                        if not effect:
                            raise ValueError("That earlier color edit is no longer available.")
                        effect.color = action.color
                    else:
                        if len(after.visual_edits) >= 6:
                            raise ValueError(
                                "This reel already has six color selections. Reuse an existing one or undo a change."
                            )
                        selection = director.locate_color_target(
                            before, folder(before) / "source.mp4", action.target
                        )
                        mask_model = mask_model_info()
                        after.visual_edits.append(
                            RecolorEffect(
                                **selection.model_dump(),
                                target=action.target,
                                color=action.color,
                                mask_model=mask_model["name"] if mask_model else "opencv",
                                mask_model_sha256=mask_model["sha256"] if mask_model else None,
                            )
                        )
                elif action.type == "sound_pass":
                    if after.objects:
                        raise ValueError(
                            "This reel already has sound layers. Ask for a specific change instead."
                        )
                    after = director.analyze(after, path, action.brief)
                    if not after.cues:
                        raise ValueError(
                            "I couldn't find clear sound-producing actions in this shot. Try a color change or ambient music instead."
                        )
            after = Project.model_validate(after.model_dump())
            library.validate(after)
            prepare_preview(after, folder(before))
            if after.music:
                library.music_path(after)
            return {
                "project": studio.commit(workspace, before, after),
                "message": direction.message,
            }

    @app.post("/api/projects/{project_id}/command")
    def command(request: Request, project_id: str, body: CommandRequest):
        before = studio.get(owner(request), project_id, body.revision)
        studio.object(before, body.object_id)
        if body.cue_id and studio.cue(before, body.cue_id).object_id != body.object_id:
            raise ValueError("Select a cue on the selected object.")
        with media_slot():
            direction = director.command(before, body.object_id, body.cue_id, body.instruction)
            after = (
                studio.edit(
                    owner(request),
                    project_id,
                    EditRequest(
                        revision=before.revision,
                        object_id=body.object_id,
                        cue_id=body.cue_id,
                        operations=direction.operations,
                    ),
                )
                if direction.operations
                else before
            )
            return {"project": after, "message": direction.message}

    @app.post("/api/projects/{project_id}/assets")
    async def asset_upload(
        request: Request,
        project_id: str,
        file: UploadFile = File(),
        revision: int = Form(),
    ):
        before = await run_in_threadpool(studio.get, owner(request), project_id, revision)
        if len(before.assets) >= 16:
            raise ValueError("A scene supports up to 16 creator recordings.")
        filename = Path(file.filename or "My recording").name
        asset_id = f"user_{new_id()}"
        target = folder(before) / "assets" / f"{asset_id}.wav"
        with media_slot():
            try:
                async with uploaded(file) as source:
                    duration = await run_in_threadpool(normalize_audio, source, target)
                    after = before.model_copy(deep=True)
                    after.assets.append(
                        Asset(id=asset_id, name=Path(filename).stem[:100], duration=duration)
                    )
                    return await run_in_threadpool(studio.commit, owner(request), before, after)
            except Exception:
                target.unlink(missing_ok=True)
                raise

    @app.get("/api/projects/{project_id}/assets/{asset_id}.wav")
    def asset_get(request: Request, project_id: str, asset_id: str):
        project = studio.get(owner(request), project_id)
        if not any(asset.id == asset_id for asset in project.assets):
            raise NotFound("Recording not found in this project.")
        return FileResponse(library.path(project, asset_id), media_type="audio/wav")

    @app.post("/api/transcribe")
    async def transcribe(file: UploadFile = File()):
        if not director.configured:
            raise DirectorUnavailable(
                "Foundry transcription is unavailable. Type your direction instead."
            )
        with media_slot():
            async with uploaded(file) as source:
                target = source.with_suffix(".wav")
                try:
                    await run_in_threadpool(normalize_audio, source, target, 30)
                    text = await run_in_threadpool(director.transcribe, target)
                    if not text:
                        raise ValueError(
                            "No speech was recognized. Try again or type your direction."
                        )
                    return {"text": text}
                finally:
                    target.unlink(missing_ok=True)

    @app.post("/api/projects/{project_id}/exports")
    def export(request: Request, project_id: str, body: Versioned):
        project = studio.get(owner(request), project_id, body.revision)
        with media_slot():
            result = render_export(project, library, folder(project))
            root = f"/api/projects/{project_id}/exports/{result['id']}"
            result.update(
                {
                    "video_url": f"{root}/video",
                    "bundle_url": f"{root}/bundle",
                    "project_url": f"{root}/project",
                    "mix_url": f"{root}/mix",
                }
            )
            directories = sorted(
                (folder(project) / "exports").iterdir(),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            for old in directories[3:]:
                if old.is_dir() and re.fullmatch(r"[a-f0-9]{32}", old.name):
                    shutil.rmtree(old)
            return result

    @app.get("/api/projects/{project_id}/exports/{export_id}/{kind}")
    def export_file(
        request: Request,
        project_id: str,
        export_id: str,
        kind: Literal["video", "bundle", "project", "mix"],
    ):
        project = studio.get(owner(request), project_id)
        if not re.fullmatch(r"[a-f0-9]{32}", export_id):
            raise NotFound("Export not found.")
        filenames = {
            "video": "film.mp4",
            "bundle": "bundle.zip",
            "project": "project.json",
            "mix": "mix.wav",
        }
        filename = filenames[kind]
        path = folder(project) / "exports" / export_id / filename
        if not path.is_file():
            raise NotFound("This export is no longer available. Render it again.")
        slug = re.sub(r"[^a-zA-Z0-9_-]", "-", project.name).strip("-") or "foleygraph"
        return FileResponse(path, filename=f"{slug}-{filename}")

    if settings.web_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.web_dir, html=True), name="studio")
    else:

        @app.get("/")
        def frontend_missing():
            return JSONResponse(
                {"detail": "Build the studio with: cd web && npm ci && npm run build"},
                status_code=503,
            )

    return app


app = create_app()
