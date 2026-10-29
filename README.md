# FoleyGraph

**Describe it. See it. Share it.**

A mobile-first, conversational reel editor with detailed Foley controls when needed. React and
TypeScript run the editor and Web Audio preview. One FastAPI App Service handles Azure
OpenAI, media processing, and FFmpeg exports. Azure Table Storage persists the editable
project graph. There is no graph database, GPU service, Redis, rendering service, or
external sound-generation API.

For complete startup, configuration, architecture, deployment, and troubleshooting
instructions, see the [implementation and operator runbook](IMPLEMENTATION.md).
The clean public source is at <https://github.com/ShemManyu/FoleyGraph>.

## What works

- Upload a clip, remix **Weekend, remixed**, with real people outdoors, or choose the
  **Slow mornings** portrait cafe reel. Both demos use licensed stock video.
- Describe visual or sound changes in chat. Foundry resolves targets from the clip,
  scene state, and recent conversation without requiring a tool or layer selection.
- Mobile puts the conversation first: a compact, expandable reel preview, one message
  bar for text or voice, and Share. Extra tools live in More, not the main workspace.
- Recolor an existing visible surface, such as the shirt of the person on the right.
  Foundry selects numbered, image-derived surfaces from close-up frame samples instead
  of relying on guessed pixel coordinates. Optional **Meta SAM 2.1 Hiera Tiny**
  image masks, source-color boundaries, CPU GrabCut, and optical flow refine the
  result while preserving shading and neighboring surfaces.
  The preview and exported video use the same result.
- Add original ambient instrumental music, replace the original soundtrack, or remove
  the music again. Color edits retain original audio unless explicitly changed.
- Add, change, or remove a short on-video title through chat. Titles are rendered into
  the same preview and MP4 as color edits, and support undo and portable project export.
  This does not remove text already burned into an uploaded source.
- Share the actual finished MP4 through the phone's native share sheet, including
  installed Instagram/WhatsApp targets. Unsupported browsers offer the MP4 download.
- Select individual objects in the video through editable, interpolated box tracks.
- Ask Foundry to propose distinct objects, action cues, and approximate visual bindings.
- Direct the selected object's sounds in plain language or transcribe a spoken direction.
  Model-proposed tool calls are validated and restricted to that object, and optionally one cue.
- Replace one character's footsteps without changing its rhythm or another character's layer.
- Use 32 original procedural CC0 samples, import a recording, or record through the microphone.
- Add and delete actions; correct timing by frame; adjust duration, gain, speed, stereo
  placement, filtering, and fades. Auto pan follows the object's screen position.
- Preview independent layers with mute and preview-only solo. Undo the last 20 edits.
- Export a finished MP4, isolated stereo WAV layers, a stereo mix, and editable project JSON.
  Reimport the complete ZIP to reopen the project, including its silent source and recordings.
- Save automatically to a browser-specific workspace with optimistic revision checks.

The people demo starts with a silent portrait excerpt, without precomputed edits or a
prepared sound graph. Its outfit, title, and music changes are actual chat-driven edits.
The cafe demo has a prepared portrait crop, color treatment,
plus explicitly **hand-authored** sound layers and approximate boxes. Titles can be added
through chat instead of being burned into the source. These initial
layers are not presented as an AI analysis result. Cafe footage is by
[WIERZBA PH on Pexels](https://www.pexels.com/video/pouring-water-into-coffee-cup-14364305/),
and the people clip is
[Two Men Engaging in Conversation Outdoors](https://www.pexels.com/video/two-men-engaging-in-conversation-outdoors-34708066/).
Both use the [Pexels License](https://www.pexels.com/license/). Provenance is recorded in
`server/assets/demo/credits.json` and preserved in the exported project notes.
Its pour, ceramic resonance, and room tone are original procedural CC0 sound design,
not field recordings. The separate 32-sound library remains original CC0 material.
No stock download or external media request is needed at runtime.

## Run locally

Requires Python 3.11+ and Node.js 22+. FFmpeg is bundled by `imageio-ffmpeg`; no system
FFmpeg installation, Docker, or Azure account is required for manual editing and exports.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
npm --prefix web ci
npm --prefix web run build
.venv/bin/python scripts/run_local.py
```

Open <http://127.0.0.1:8000>. Local projects and media live in `.data/local/`.

To develop the UI with live reload, keep the Python server running and run:

```bash
npm --prefix web run dev
```

Vite proxies API and media requests to port 8000.

### Enable Foundry locally

The deployed models are `foleygraph-director` (GPT-5.4 mini with vision/tool calling)
and `foleygraph-transcribe` (GPT-4o mini Transcribe). Foundry handles conversation,
visual grounding, and transcription. The optional Meta model below provides actual
learned image-anchor masks on the same CPU App Service.
The director has an 80,000-token/minute GlobalStandard quota allocation to accommodate
consecutive visual edits without immediately exhausting the original 20,000-token allowance.

With Azure CLI logged into the target subscription:

```bash
.venv/bin/python scripts/run_local.py --azure
```

This helper retrieves the dedicated resource's API key into process memory only. It
does not write or print credentials, and it still uses **local SQLite**, not the
production project table. The deployed application uses managed identity, not this key.

For another Foundry resource, export the variables documented in `.env.example`.
Environment files are not loaded automatically. Without Foundry configuration, the
editor explicitly reports manual mode; no fabricated AI output is substituted.

### Enable Meta image masks

The [reviewed CPU bundle](https://github.com/ShemManyu/FoleyGraph/releases/tag/meta-sam2.1-cpu-v2)
is public. Reproducible export instructions and the latest download verification are in
[the runbook](IMPLEMENTATION.md#optional-meta-sam-21-masks).
The installer uses an identical, versioned mirror on the project's existing Azure
Storage website, with no login or model account required.

```bash
.venv/bin/python scripts/prepare_meta_model.py
.venv/bin/python scripts/run_local.py --azure
```

The downloader verifies both ONNX files before installing the approximately 126 MB
bundle. Restart after preparation. `/api/config` reports the verified model identity;
successful new recolor effects persist its hash. Existing CV edits keep their original
provider. Missing optional assets retain CV behavior; corrupt or mismatched assets and
unrenderable Meta edits fail instead of claiming a successful model-backed edit.

This uses official SAM 2.1 image anchors plus FoleyGraph's CPU temporal tracking,
not SAM 3 or the full SAM video-memory predictor. Production requires ONNX Runtime,
not Torch, CUDA, or a separate model service. Meta's code and checkpoint remain
Apache-2.0, with attribution and the license in [`LICENSES/SAM2.txt`](LICENSES/SAM2.txt).

## Use the studio

1. Upload a permitted clip up to 20 seconds and 100 MB, or choose **Try the demo**.
2. Describe what you want: "Make the left outfit terracotta", "Make the coffee pour
   quieter", "Add the title 'SAME CREW. NEW MOOD.'", or "Add ambient music".
   If a target/color is unclear, answer the chat's
   short question. No layer selection is required.
3. Use **+** in chat to record or upload your own sound. Apply it from its conversation
   card. Say **Undo that** or use Undo to return to the previous version.
4. Choose **Share reel**, then Instagram or WhatsApp on a supported phone. Choose the
   app in the native share menu. Other browsers can save the MP4 and attach it manually.
   **Keep the project files and sound layers** reveals the portable bundle and WAV.

The default workspace shows only the preview and conversation. **More > Advanced tools** reveals
object bindings, material selection, cue timing, mix controls, and the timeline when
you want them. Nothing in those detailed controls is required to try the demo.
The preview can expand for a closer look and collapses when you start typing.
Starter suggestions disappear after the first direction, leaving room for the conversation.
Chat history is saved in this browser, not exported with bundles. The last 12 messages
are sent with the next direction to support follow-ups. A phone-sized workspace keeps
the video, latest messages, and composer in view, including when the keyboard opens.

Web browsers cannot force Instagram or WhatsApp as a native share target or confirm
publication. The app prepares the file before the share tap to preserve browser user
activation, and never claims the video was posted. No social account tokens are stored.

Text direction examples:

```text
Change the shirt of the guy on the right to blue.
Add ambient music.
Make the coffee pour a little quieter.
Make the left character's footsteps metallic, but keep the rhythm.
Move this impact two frames earlier.
Make this layer 3 dB quieter.
Muffle these footsteps.
```

`Space` plays/pauses, arrow keys step the preview one frame, `Ctrl/Cmd Z` undoes, and
Delete removes a selected cue. **M** persists a layer mute. **S** solos only in preview;
solo, preview volume, and preview mute do not change exported audio.

Sound imports use at most the first five seconds, trim leading/trailing silence, and
normalize the peak. The full prepared recording is reused at each assigned action.
New uploads retain their original soundtrack separately from the silent video. Adding
music layers it underneath; replacing music can mute that entire original track.
Dialogue and music in a mixed source are not separated. Undo restores the previous mix.

## Limits and honest boundaries

- One uninterrupted clip, up to 20 seconds, three objects, 100 action cues, and 16 custom
  sounds of up to five seconds each. Video is normalized to silent H.264 MP4, at most
  1280 pixels on either axis and 60 fps.
- Up to six regional recolor selections. Outlines, visibility, color discrimination,
  and optical flow are approximate, especially on fast motion, occlusions, similar
  colors, disconnected garment parts, or patterned clothing. Uncertain targets and
  unrenderable masks are rejected without saving a fake edit. This is not generative
  clothing replacement or video generation.
- The cafe clip's pale cup and same-colored saucer are a difficult recoloring case.
  The editor may refuse that selection. Use the people demo for outfit recoloring
  and the cafe demo for selective sound edits; neither implies perfect segmentation.
- Foundry uses up to 24 timestamped frames to propose boxes and contacts. These are
  **editable box tracks**, not SAM segmentation, pixel-accurate tracking, or guaranteed
  instance identity across cuts and occlusions. Correct boxes at individual frames or
  mark visibility through the API. Multi-shot reidentification is out of scope.
- An object being visible never creates continuous audio. Only explicit action cues sound.
- Contact times are estimates. Inspect and adjust them; no perfect automatic footstep
  synchronization is promised.
- Preview uses Web Audio; export uses deterministic 48 kHz PCM rendering and AAC muxing.
  Browser resampling, filtering, and master compression can sound slightly different.
  Only the exported master mix is peak-limited. Isolated layers preserve their gains.
- Ambient music is original procedural synthesis, not an arbitrary-song generator.
  No production-audio separation, dialogue repair, automatic Instagram publication,
  face replacement, object insertion, or multi-shot editing is implied.
- Anonymous browser workspaces are isolated with signed HTTP-only cookies, not accounts
  or a collaboration system. Clearing cookies loses access. Export a bundle for backup.
  Add organization authentication and stronger distributed quotas before a broad public
  launch involving private client footage or many concurrent creators.

Only upload footage and recordings you own or have permission to use. Analysis sends
sampled visual frames, scene state, recent chat, and the direction to Azure OpenAI. Spoken direction sends
the recording for transcription. Sound imports themselves are processed locally by
the application, not sent to an audio-generation service.

## Verify

```bash
.venv/bin/ruff check server tests scripts
.venv/bin/ruff format --check server tests scripts
.venv/bin/python -m pytest -q
.venv/bin/python scripts/verify_regressions.py
npm --prefix web run lint
npm --prefix web run format:check
npm --prefix web run build
cd web && npx playwright install chromium && npm run test:e2e
```

The regression harness deliberately breaks audio scope, same-color person isolation,
touching-surface separation, coarse-region correction, and clipped-white color matching **in memory**. Each focused
test must fail against its corresponding bug. The displayed assertion failures are
expected; the harness succeeds only if every mutation is caught. Source files are
never mutated by the harness.

Backend tests cover untouched-layer PCM equality, preserved rhythm, foreign cue rejection,
stale revisions, branched undo, visibility without audio, AI proposal validation, browser
workspace isolation, range requests, upload/binding, custom sounds, and export/reimport.
Browser tests exercise material changes, undo, frame correction, actual media playback,
microphone recording, custom sound assignment, downloads, imports, and mobile layout.

The GitLab pipeline runs backend checks and the frontend lint/typecheck/build. Browser
tests run locally. A GitLab runner must be available for CI; no deployment credentials
are committed to CI.

## Event-built contributions

The original repository contained only a README. FoleyGraph's implementation commits
are dated October 29, 2026, after the event's published October 26 kickoff.
The team-built work is the chat-first mobile editor, editable project/revision graph,
image-grounding and CPU mask/tracking integration, source-preserving recoloring and
titles, scoped procedural sound design, exports, and single-service Azure deployment.
The contribution is integrating real model outputs into an editable temporal workflow,
not training a new foundation model or generating the stock scene.

Meta supplies SAM 2.1; OpenAI supplies the vision/language and speech models; Azure
supplies hosting and persistence. React, OpenCV, ONNX Runtime, and FFmpeg are upstream
dependencies. Pexels supplies the licensed footage. These are not team-built assets.
See the runbook's checkpoint ledger for actual validation and deployment state.

WhatsApp currently means native MP4 sharing, **not WABA automation**. No Cloud API
webhook, business-profile assistant, or automatic message delivery is implemented.
Public source, model use, and recorded code dates do not establish participant
acceptance, track/team details, or final event eligibility.

## Azure deployment

Target: subscription `85041044-a067-4f83-8afd-599930e74e7d`, tenant
`794201fa-773d-487f-8c6f-44b2df286e78`, resource group `Meta-Foolio`.

| Resource | Name | Purpose |
|---|---|---|
| Linux App Service plan | `foleygraph-plan` | One B1 worker |
| App Service | `foleygraph-fokas` | API, browser studio, audio rendering |
| Storage account | `foleygraphfokas1029` | Standard LRS Table Storage |
| Project table | `foleygraph` | Versioned, compressed editable JSON |
| Azure OpenAI account | `foleygraph-foundry` | Dedicated vision director and transcription |

Resources are in East US 2; the existing resource group's location remains unchanged.
The app's system-assigned identity has **Storage Table Data Contributor** on its storage
account and **Cognitive Services OpenAI User** on its dedicated OpenAI account.
No storage keys or OpenAI keys are needed in App Service settings.

```bash
az login --tenant 794201fa-773d-487f-8c6f-44b2df286e78
.venv/bin/python scripts/deploy.py
```

The script uses the explicit subscription on every Azure call, reuses existing resources,
preserves the workspace-signing secret, builds the browser app, and packages only runtime
files. It submits an asynchronous Oryx deployment, waits for that specific build to finish,
then checks HTTPS, the exact backend source fingerprint and built application shell,
Table Storage readiness, and the expected mask-model identity. Run checks before
deployment. `--skip-build` reuses a verified build;
`--skip-provision` is for an already provisioned and configured environment.

Default address: <https://foleygraph-fokas.azurewebsites.net>

The B1 plan is billed while idle. OpenAI and storage are usage-billed. Resource creation
requires management permissions, role-assignment permission, and model quota.

### Persistence and operations

Editable project states and the 20 retained undo snapshots are compressed into separate
Azure Table entities, each below the 64 KiB binary-property limit. Revisions and ETags
prevent stale writes. Media, recordings, and the three most recent export bundles per
scene live under persistent **`/home/foleygraph`** with
`WEBSITES_ENABLE_APP_SERVICE_STORAGE=true`. No Blob container is required.

Keep one App Service instance and one Uvicorn worker. Heavy media/model work is limited
to one request at a time; ordinary reads and editing remain available. This is a simple
short-film studio, not a distributed rendering queue. App Service disk quota still applies.
Deleting a scene removes its table state, undo snapshots, and media. Export important
projects and arrange backups before changing the app's persistent filesystem.

`GET /healthz` checks storage readiness, AI configuration, and the backend fingerprint
captured at worker startup; it does not perform a model inference.
Azure App Service health checks use that endpoint.
`WORKSPACE_SECRET` must remain stable across deployments so existing browser workspaces
retain access. HTTPS, same-origin editing, cookie isolation, bounded uploads, media format
whitelisting, and server-side tool-call validation are enabled by default.
