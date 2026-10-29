# FoleyGraph implementation and runbook

This guide describes the application that exists today and how to run it.
Run commands from the repository root unless a section says otherwise.

**Current scope:** a browser-based, chat-first video and Foley editor.
WhatsApp support currently means sharing or downloading the finished MP4.
There is **no WhatsApp Business Platform/Cloud API integration**, incoming
WhatsApp webhook, business-profile assistant, booking system, or automated
WhatsApp reply. Native sharing is not WABA automation.

Deployed application: <https://foleygraph-fokas.azurewebsites.net>

## 1. Prerequisites

| Requirement                                         | Notes                                                                      |
| --------------------------------------------------- | -------------------------------------------------------------------------- |
| Repository access                                   | [Public source on GitHub](https://github.com/ShemManyu/FoleyGraph).        |
| Python 3.11 or 3.12                                 | Azure runs Python 3.12; local verification also uses 3.11.                 |
| Node.js 22.13 or newer in the 22.x series, with npm | Required by the locked frontend/build/lint dependencies.                   |
| A modern browser                                    | Chrome/Chromium is used for automated browser checks.                      |
| Azure CLI                                           | Only needed for Azure authentication, the `--azure` helper, or deployment. |

The commands below target macOS, Linux, or Windows through WSL.
No Docker, GPU, Redis, SQL server, or system FFmpeg installation is required.
`imageio-ffmpeg` supplies the FFmpeg binary.

Azure is optional for local manual editing and exports. Conversational edits,
visual understanding, and speech transcription require configured Azure OpenAI.

## 2. First local run

For a fresh checkout:

```bash
git clone https://github.com/ShemManyu/FoleyGraph.git foleygraph
cd foleygraph
```

If the repository is already checked out, start from that directory:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
npm --prefix web ci
npm --prefix web run build
.venv/bin/python scripts/run_local.py
```

Open <http://127.0.0.1:8000>. Stop the server with `Ctrl+C`.

The build command runs TypeScript checking followed by Vite. FastAPI serves the
built `web/dist/` files, so the normal local run needs only one server.
Keep `requirements.lock` alongside `requirements.txt`; it constrains runtime
dependency versions.

The local helper always:

- Binds to `127.0.0.1`, using port `8000` unless `--port` is supplied.
- Uses SQLite and media under `.data/local/`.
- Overrides `AZURE_STORAGE_ACCOUNT` to empty, avoiding the production table.

For an occupied port:

```bash
.venv/bin/python scripts/run_local.py --port 8001
```

### Confirm startup

In another terminal:

```bash
curl --fail http://127.0.0.1:8000/healthz
```

With no Azure OpenAI endpoint configured, expect:

```json
{
  "status": "ok",
  "storage": "sqlite",
  "ai_configured": false,
  "version": "1.0.0",
  "backend_revision": "<64-character runtime-source fingerprint>"
}
```

`ai_configured: false` is a valid manual-mode startup, not a failed installation.
Use **Coffee ritual > Try the demo** to hear the prepared Foley, open
**More > Advanced tools** for manual controls, and export through **Share reel**.
The default people demo starts silent, without prepared effects.

If the landing page returns `503` with "Build the studio", build the frontend.
If it opens but chat editing is unavailable, configure Foundry below.

## 3. Enable real Foundry/OpenAI editing

### Use this project's existing Azure account

This requires access to the target tenant/subscription and permission to retrieve
the dedicated account's key:

```bash
az login --tenant 794201fa-773d-487f-8c6f-44b2df286e78
.venv/bin/python scripts/run_local.py --azure
```

`--azure` uses these fixed resources:

| Setting                  | Value                                           |
| ------------------------ | ----------------------------------------------- |
| Subscription             | `85041044-a067-4f83-8afd-599930e74e7d`          |
| Resource group           | `Meta-Foolio`                                   |
| Azure OpenAI account     | `foleygraph-foundry`                            |
| Endpoint                 | `https://foleygraph-fokas-ai.openai.azure.com/` |
| Director deployment      | `foleygraph-director`                           |
| Transcription deployment | `foleygraph-transcribe`                         |

The helper retrieves the key into process memory. It does not print it or write
it to a file. Persistence remains **local SQLite**, even with `--azure`.
It does not provision resources, deploy the app, or change production settings.

### Use your own Azure OpenAI resource

Use deployment names, not base model names. The current director uses GPT-5.4 mini
with vision, tool calling, and reasoning-effort options; another deployment must
support the API features used in `server/director.py`.

For Entra authentication, first use `az login` with an identity that has
**Cognitive Services OpenAI User** access on your resource:

```bash
export AZURE_OPENAI_ENDPOINT="https://YOUR-RESOURCE.openai.azure.com/"
export AZURE_OPENAI_DEPLOYMENT="YOUR-DIRECTOR-DEPLOYMENT"
export AZURE_OPENAI_TRANSCRIPTION_DEPLOYMENT="YOUR-TRANSCRIPTION-DEPLOYMENT"
.venv/bin/python scripts/run_local.py
```

Leave `AZURE_OPENAI_API_KEY` unset when using Entra authentication. Alternatively,
inject that variable through your local secret-management workflow to use an API
key. Never commit keys, include them in URLs, or paste them into issue reports.
Set the transcription deployment to an empty string if voice input is not needed.

**`.env` files are not loaded automatically.** `.env.example` documents variable
names; copying it to `.env` alone does not configure the application.
Do not pass `--azure` for a custom resource, because it replaces these values
with the project's fixed Azure configuration.

### Verify the AI path

Open **People & style > Try the demo**, then send these as three separate
messages, waiting for each edit to finish before sending the next:

```text
The guy on the left should be terracotta.
Add the title 'WEEKEND, REMIXED' and warm ambient music.
Make his outfit sage green instead. Keep the title and music.
```

Confirm the visible result, then download the MP4 through **Share reel**.
The title spans the whole clip; custom title timing is not supported.

`/healthz` only checks storage and reports AI configuration. It does not perform
an inference or prove that credentials, deployment names, or quota work.
Model calls send sampled frames, scene state, recent conversation, and editing
instructions to Azure OpenAI. Voice instructions are sent for transcription.

### Optional Meta SAM 2.1 masks

Foundry still resolves the instruction and grounds the requested surface. The
optional local Meta model supplies real learned masks for that selection.
It is **SAM 2.1 Hiera Tiny image-anchor inference**, not SAM 3, not newly trained
weights, and not the full SAM video-memory predictor.

The [reviewed prepared bundle](https://github.com/ShemManyu/FoleyGraph/releases/tag/meta-sam2.1-cpu-v2)
is public. Stop the application and run:

```bash
.venv/bin/python scripts/prepare_meta_model.py
.venv/bin/python scripts/run_local.py --azure
```

Download mode verifies the two reviewed ONNX hashes, retains Meta's license,
and writes the manifest last. It needs no Torch installation or model account.
The default download uses the identical
[versioned Azure mirror](https://foleygraphfokas1029.z20.web.core.windows.net/models/meta-sam2.1-cpu-v2/manifest.json);
GitHub retains the reviewed release as a second public distribution.
Allow time for the transfer: progress is reported every 10 MiB, and each file has
a 15-minute transfer budget plus a 30-second socket inactivity timeout.
Approximately 126 MB is installed under
`server/assets/models/sam2.1-hiera-tiny/`, which is ignored by Git but included
in the application deployment package.

Check `GET /api/config`: `mask_model` is `null` without the optional manifest,
otherwise it includes the actual model name, weight fingerprint, input size,
checkpoint hash, and pinned Meta source revision. A successful new recolor
persists `mask_model` and `mask_model_sha256`; it is committed only after the
render succeeds. Existing CV effects retain `opencv`, even when the optional
model is installed later. A portable Meta-backed project requires its matching
model bundle to render.

The reviewed combined model fingerprint is:

```text
d36e9d0c438cc2278b1d32de89ccaf4352ea44d8cc9339f610bc3ced4b7d0a9a
```

The v2 bundle uses a 512-pixel encoder input. The original v1 768-pixel bundle
remains recognized, with its own image/prompt scale and unchanged fingerprint
`842f7b7fd7c74b1bf64c80b96358f6c88ff315005300def7e6e5f6ab14d9c37c`.
Changing the installed bundle does not relabel old effects: their saved weight
fingerprint must still match. Use the matching bundle to render an old project.

ONNX Runtime executes on CPU with one inference thread. SAM runs at grounding
anchors, with a one-second maximum refresh gap for sparse controls. Between
anchors, dense optical flow propagates model-derived support. For fabric only,
a convex envelope of that support bridges temporary hand/fold occlusions,
without extending its outer spatial bounds. Object-mask holes are not filled
this way. Bounded source-surface snapping repairs small boundary gaps only on
color components already almost entirely supported by the tracked envelope.
Current source-color matching, grounding and protected points still restrict
every recolored pixel. This is approximate hybrid tracking, not a promise of
pixel-accurate identity through occlusion.

Grounded fabric vertices explicitly on the image edge stay on that edge during
affine tracking. Otherwise shirt motion can drag a cropped trouser boundary
inward and clip still-visible fabric. The grounding can move off the edge in
later anchors; source color, connected components, Meta support and protection
still gate recoloring. This never generates missing video pixels. New previews
use `surface-v18` so cached edge gaps are not reused for an edit.

Each inference sees immutable original pixels, not another recolor or a title.
Invalid weights, low-confidence output, missed foreground points, protected-point
violations, and unrenderable selections reject the edit. Do not silently relabel
a CV render as Meta-backed. Restart after model preparation because verified
metadata and inference sessions are cached.

The encoder also caches up to eight identical resized original frames in memory,
keyed by pixels, input size and model fingerprint. Follow-up colors or titles can
reuse those features; prompts, decoder output, confidence and protection checks
are still evaluated anew. The cache is bounded, process-local and lost at restart.
Meta preview processing has a 300-second deadline; CV-only processing retains
120 seconds. Model loading, planning and output finalization add overhead, so
these are not total request-latency guarantees. Short clips are recommended on B1.
The browser uses the asynchronous edit workflow below so those waits do not
depend on one long HTTP connection.

#### Reproduce the conversion instead of downloading

Use an isolated optional tool environment, never the application's production
environment:

```bash
python3 -m venv .data/model-tools
.data/model-tools/bin/python -m pip install \
  wheel==0.45.1 torch==2.7.1 torchvision==0.22.1 onnx==1.17.0
SAM2_BUILD_CUDA=0 .data/model-tools/bin/python -m pip install --no-build-isolation \
  "git+https://github.com/facebookresearch/sam2.git@2b90b9f5ceec907a1c18123530e92e794ad901a4"
SAM2_BUILD_CUDA=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  .data/model-tools/bin/python scripts/prepare_meta_model.py --export
```

On Linux, use the official PyTorch CPU wheel index for the Torch/TorchVision
installation if avoiding optional CUDA downloads. The exporter checks the
official checkpoint hash, pinned source provenance, and tool versions, then
validates ONNX structure. It can reuse a verified local checkpoint through
`--checkpoint PATH`. The reviewed export was reproduced byte-for-byte locally;
do not assume another conversion has the same fingerprint without checking it.
Meta's license is retained in `LICENSES/SAM2.txt` and the prepared model folder.
That third-party license is not an application-wide license grant.

## 4. Development and configuration

For frontend hot reload, keep the backend on port `8000` in one terminal:

```bash
.venv/bin/python scripts/run_local.py
```

In a second terminal:

```bash
npm --prefix web run dev
```

Open the Vite URL printed in that terminal, normally
<http://127.0.0.1:5173>. Vite proxies `/api` and `/healthz` to port `8000`.
`run_local.py` does not enable Python autoreload; restart it after backend changes.

For an isolated data directory, bypass the local helper's fixed directory:

```bash
AZURE_STORAGE_ACCOUNT= FOLEYGRAPH_DATA_DIR=.data/my-workspace \
  .venv/bin/python -m uvicorn server.main:app --host 127.0.0.1 --port 8000
```

| Variable                                | Behavior                                                                                             |
| --------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `FOLEYGRAPH_DATA_DIR`                   | Raw application default: `.data/`. Local helper: `.data/local/`. Azure: `/home/foleygraph`.          |
| `AZURE_STORAGE_ACCOUNT`                 | Empty selects SQLite; a name selects Azure Table Storage with Entra credentials.                     |
| `AZURE_STORAGE_TABLE`                   | Defaults to `foleygraph`. The Azure table must already exist.                                        |
| `AZURE_OPENAI_ENDPOINT`                 | Empty disables AI. Supply the Azure OpenAI resource endpoint, not a Foundry project URL.             |
| `AZURE_OPENAI_DEPLOYMENT`               | Defaults to `foleygraph-director`.                                                                   |
| `AZURE_OPENAI_TRANSCRIPTION_DEPLOYMENT` | Defaults to `foleygraph-transcribe`; empty disables voice transcription.                             |
| `AZURE_OPENAI_API_KEY`                  | Optional local key; otherwise `DefaultAzureCredential` is used. Production uses managed identity.    |
| `WORKSPACE_SECRET`                      | Required on App Service. Locally generated in `<data-dir>/.workspace-secret` if absent. Keep stable. |

The complete supported settings are in `server/config.py`.
Upload/media limits are application settings in code, not additional environment
variables.

## 5. How the implementation works

```text
React studio + Web Audio
        |
        | same-origin HTTP, signed workspace cookie
        v
FastAPI: validation, revisions, one heavy-processing slot
        |
        +--> Azure OpenAI: planning, visual grounding, transcription
        +--> optional Meta SAM 2.1 / ONNX Runtime: learned image-anchor masks
        +--> OpenCV/Pillow: source-color refinement, tracking, full-clip titles
        +--> procedural audio + FFmpeg: preview/export media
        +--> SQLite locally OR Azure Table Storage in production
        +--> local media files OR persistent /home/foleygraph on Azure
```

| Location                                    | Responsibility                                                            |
| ------------------------------------------- | ------------------------------------------------------------------------- |
| `web/src/App.tsx`                           | Mobile-first editor, conversation, uploads, share/download UI.            |
| `web/src/audio.ts`                          | Browser preview of separate sounds, original audio, and music.            |
| `server/main.py`                            | HTTP endpoints, workspace isolation, validation, processing lock.         |
| `server/models.py`, `server/studio.py`      | Editable graph, scoped operations, revisions, undo.                       |
| `server/director.py`                        | Foundry planning, frame-grounded surface selection, speech transcription. |
| `server/visual.py`                          | CPU recoloring, optical-flow tracking, caption compositing.               |
| `server/segmentation.py`                    | Verified optional Meta model, image inference, mask refinement/flow.      |
| `scripts/prepare_meta_model.py`             | Checksum-verified model download or reproducible optional conversion.     |
| `server/audio.py`, `server/media.py`        | Procedural sounds/music, normalization, rendering, ZIP import/export.     |
| `server/storage.py`                         | SQLite and Azure Table state/history stores.                              |
| `server/demo.py`, `server/assets/demo/`     | Licensed stock clips and prepared cafe sound graph.                       |
| `scripts/run_local.py`, `scripts/deploy.py` | Local startup and fixed-target Azure deployment.                          |

Recoloring is not generative video replacement. Foundry first resolves the target,
then examines immutable source frames and selects numbered image-derived
components. CPU masks and tracking apply the new color while preserving shading.
Titles are composited separately. The preview and exported video use the same
prepared result.

Music and the sound library are original procedural synthesis, not an external
sound-generation service. The cafe's initial Foley is explicitly hand-authored.
The people demo has no prepared AI edits. Credits and license links are preserved
in project exports.

### API notes for integrators

Interactive Swagger/ReDoc pages are disabled. The machine-readable schema is at
`GET /openapi.json`.

| Endpoint                          | Purpose                                                                   |
| --------------------------------- | ------------------------------------------------------------------------- |
| `GET /healthz`, `GET /api/config` | Readiness and feature configuration.                                      |
| `POST /api/demo?scene=style`      | Create the real-people demo.                                              |
| `POST /api/demo?scene=coffee`     | Create the prepared cafe demo. The API's omitted-scene default is coffee. |
| `POST /api/projects`              | Upload a video as multipart `file`.                                       |
| `POST /api/projects/{id}/direct`  | Apply conversational direction.                                           |
| `GET /api/jobs/{job_id}`          | Poll a private, process-local asynchronous edit receipt.                  |
| `POST /api/projects/{id}/exports` | Create MP4, WAV mix, project JSON, and portable ZIP.                      |
| `POST /api/projects/import`       | Import a portable ZIP as multipart `file`.                                |

Clients must retain the workspace cookie between requests. A different browser
workspace cannot access the project just by knowing its ID.
Send the current project revision for edits and exports.

Example direction body:

```json
{
  "revision": 0,
  "instruction": "Add the title 'MY REEL' and ambient music.",
  "history": []
}
```

A clarification can return HTTP `200` with an unchanged revision. Verify the
returned project and revision, not just the HTTP status.
The export endpoint requires a JSON body, for example `{"revision": 1}`;
omitting the body returns `422`.

The browser sends `Prefer: respond-async` to `/direct`. Integrators can send the
same header. Acceptance returns HTTP `202` with `status: "processing"` and a
same-origin `status_url`, also supplied in `Location`. Keep the workspace cookie
and poll that URL about once a second:

```json
{"status": "completed", "result": {"project": {}, "message": "..."}}
```

The completed result contains the full real project, abbreviated above.
While work runs, polling returns `{"status": "processing"}`. A late failure
returns `status: "failed"`, a safe `error` message, and the original `error_status`
such as `422`, `409`, or `429`. Polling itself returns `200` for known receipts;
`202` is acceptance, never proof that the edit applied. Omitting the preference
retains the original synchronous API, which is not recommended for slow CPU
recolors across App Service's HTTP timeout.

There is **no durable task queue**. At most 64 recent receipts live in the single
App Service worker. They disappear after restart or eviction; a missing or foreign
receipt returns `404`. The browser polls for at most ten minutes. On interruption,
reload the reel and inspect its revision before retrying, because a completed
edit may already be durable even if its receipt was lost. Do not automatically
resubmit an uncertain edit. A second heavy operation is rejected with `429`,
not queued. Actual media validation/rendering still precede the atomic project
commit, and a newer revision produces `409` rather than being overwritten.
Keep one Uvicorn worker and one App Service instance for this process-local
design. Scaling requires shared job state and admission control first.

## 6. Persistence and backups

| Data                                  | Local helper                   | Azure                       |
| ------------------------------------- | ------------------------------ | --------------------------- |
| Project graph and undo                | `.data/local/projects.sqlite3` | Table `foleygraph`          |
| Source, previews, recordings, exports | `.data/local/media/`           | `/home/foleygraph/media/`   |
| Generated sample library              | `.data/local/samples/`         | `/home/foleygraph/samples/` |

Azure Table stores compressed, versioned project documents and undo snapshots.
Large media stays on the App Service's persistent filesystem, not in Table
entities or a Blob container.

Back up **both metadata and media**. A database/table backup alone cannot restore
the source video or sound files. For an individual project, use
**Keep the project files and sound layers** in the export dialog to download its
portable ZIP; importing it creates a project in the receiving browser workspace.

Keep the workspace secret stable. Clearing cookies or changing the secret can
remove access to anonymous workspaces; there is no user-account recovery system.
Browser chat history is local browser state and is not included in project ZIPs.
The latest 20 undo levels and three most recent export directories are retained.
An older export URL may expire; render a new export from the retained project.

## 7. Validation

After code changes, run the applicable checks from the repository root:

```bash
.venv/bin/ruff check server tests scripts
.venv/bin/ruff format --check server tests scripts
.venv/bin/python -m pytest -q
.venv/bin/python scripts/verify_regressions.py
npm --prefix web run lint
npm --prefix web run format:check
npm --prefix web run build
```

For browser tests, build first, then:

```bash
cd web
npx playwright install chromium
npm run test:e2e
```

Playwright starts its own backend on port `8765`, uses `.data/e2e/` with SQLite,
and disables real Foundry calls. Ensure that port is free. Browser tests do not
prove live model behavior or physical iOS/Android sharing.

The regression harness deliberately reintroduces bugs **in memory**. Individual
pytest assertion failures in its output are expected; its final exit code is
zero only when the intended regressions are caught.

The GitLab pipeline runs backend checks and frontend lint/format/typecheck/build.
It does not deploy the app or run the browser suite. Shared runners have previously
failed with disk-full installation/container errors; distinguish infrastructure
failures from failing tests and do not describe such pipelines as green.

## 8. Azure operations

This section is an operator runbook, not an instruction to deploy without approval.
The deployment script is **fixed to this project's resources**, not a generic
deploy-to-any-subscription tool. Review its constants before adapting it.

| Resource                         | Current value                                    |
| -------------------------------- | ------------------------------------------------ |
| Tenant                           | `794201fa-773d-487f-8c6f-44b2df286e78`           |
| Subscription                     | `85041044-a067-4f83-8afd-599930e74e7d`           |
| Resource group / resource region | `Meta-Foolio` / `eastus2`                        |
| App / plan                       | `foleygraph-fokas` / `foleygraph-plan`, B1 Linux |
| Storage account / table          | `foleygraphfokas1029` / `foleygraph`             |
| Foundry/OpenAI account           | `foleygraph-foundry`                             |

The App Service identity needs **Storage Table Data Contributor** on the storage
account and **Cognitive Services OpenAI User** on the OpenAI account.
The current director is GPT-5.4 mini; transcription uses GPT-4o mini Transcribe.
The separate demo-narration voice deployment is not needed to run the application.

### Deploy code to the existing configured environment

Run applicable checks first. From the approved source revision:

```bash
az login --tenant 794201fa-773d-487f-8c6f-44b2df286e78
npm --prefix web run build
.venv/bin/python scripts/deploy.py --skip-build --skip-provision
```

`--skip-build` means the already-built `web/dist/` must match the source being
released. `--skip-provision` skips resource creation, role assignment, and app
configuration; it does not skip the code deployment.

For initial provisioning, an authorized operator can instead run:

```bash
.venv/bin/python scripts/deploy.py
```

That command can create resources, deploy models, assign roles, and update
production settings. It requires management/role-assignment permissions and
model quota, and can incur Azure charges.

Production uses `bash startup.sh`, one Uvicorn worker, one App Service instance,
and `FOLEYGRAPH_DATA_DIR=/home/foleygraph`.
`WEBSITES_ENABLE_APP_SERVICE_STORAGE=true` is required for persistent media.
Keep data outside the deployment directory and preserve `WORKSPACE_SECRET`.

The deployer waits for the accepted Azure build ID and checks HTTPS, storage,
AI configuration, exact built HTML, the runtime-source fingerprint, and the
expected mask-model identity. The backend fingerprint is captured once at
worker startup, so replacing files does not make an old process appear new.
**During a rolling restart, an old container can still answer health requests.**
The new source/model checks must pass before starting a long render.
In-flight edits and transient job receipts can be interrupted by recycling. The health endpoint's
`version` value is not a Git commit or proof that the new worker is serving.

Read-only diagnostics:

```bash
az webapp log deployment list --name foleygraph-fokas \
  --resource-group Meta-Foolio \
  --subscription 85041044-a067-4f83-8afd-599930e74e7d

az webapp log tail --name foleygraph-fokas \
  --resource-group Meta-Foolio \
  --subscription 85041044-a067-4f83-8afd-599930e74e7d
```

Stop log streaming with `Ctrl+C`. Do not publish raw settings, credentials,
customer media, or unredacted logs in issues. B1 is billed while idle;
OpenAI and storage also incur usage charges.

## 9. Troubleshooting and current limits

| Symptom                                             | Check or action                                                                                                                                                      |
| --------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Python import/module error                          | Use `.venv/bin/python` and install the repository's requirements, not an unrelated/global environment.                                                               |
| UI missing or old                                   | Build `web/dist/` again. The backend does not serve the TypeScript source directly.                                                                                  |
| Vite opens but API calls fail                       | Start the backend on port `8000`; that is the configured proxy target.                                                                                               |
| AI unavailable                                      | Set the endpoint/deployment and valid key or Entra identity. Manual mode is expected without them.                                                                   |
| Foundry `401`, `403`, or deployment-not-found error | Check the correct resource, credential/RBAC access, and deployment name. Do not copy another project's key or rotate a shared resource to fix this app.              |
| Studio busy / `429`                                 | Only one heavy operation runs at a time. Wait; avoid repeated submissions. Model quota can independently cause `429`.                                                |
| Edit seems slow                                     | Meta CPU editing can take minutes on B1. Processing is bounded to 180 seconds (CV-only: 120); unchanged source encodings are cached for follow-ups. Use short clips. |
| Stale revision / `409`                              | Reload the latest project before resubmitting. Do not overwrite another revision blindly.                                                                            |
| Surface cannot be isolated                          | The edit is rejected rather than fabricated. Use people footage for outfit edits; pale cup/saucer separation remains difficult.                                      |
| Meta model unavailable or hash mismatch             | Prepare the reviewed matching bundle, verify `/api/config`, and restart. Missing optional assets do not make an existing Meta-tagged project a CV project.           |
| Missing projects after clearing cookies             | Workspaces are browser-specific. Restore a previously exported ZIP; do not delete the database or media directory.                                                   |
| Microphone/native sharing unavailable               | Use HTTPS or localhost and a supporting browser/device. Desktop browsers can fall back to MP4 download.                                                              |
| Old export URL no longer works                      | Only three export directories are kept. Export again from the project.                                                                                               |
| Expected WhatsApp bot or business-data replies      | Not implemented. Sharing an MP4 is not Cloud API messaging, webhooks, or business-profile automation.                                                                |

Supported media is one uninterrupted clip, at most 20 seconds and 100 MB,
normalized to H.264 with a maximum side of 1280 pixels and at most 60 fps.
Projects support three objects, 100 action cues, 16 short custom sounds, and six
recolor selections. Masking, tracking, cue estimates, and natural-language
interpretation remain approximate. Precise relative-dB instructions are not
universally reliable.

There is no multi-shot editing, arbitrary-song generation, baked-audio source
separation, automatic Instagram publication, or confirmed Meta-program
eligibility. Only upload permitted media. Add proper account authentication and
stronger distributed quotas before a broad launch with private business footage
or many simultaneous users.

## 10. Handoff and implementation checkpoints

Update this section after each implemented and verified milestone, not just at
the end of the project. Each checkpoint must identify the change, relevant code
or commit, validation evidence, deployment state, unresolved blockers, and next
safe action. Distinguish planned work from implemented functionality. Never
include credentials, workspace cookies, customer data, or phone numbers.

### 2026-10-29: operator runbook completed

- **Change:** this runbook and its README entry point were committed as
  `a38ffb6` on `docs/implementation-runbook`.
  [Documentation MR !6](https://gitlab.com/fokas-labs/folio/-/merge_requests/6)
  is open.
- **Validation:** supported CLI flags, Markdown formatting, local SQLite startup,
  built frontend assets, OpenAPI, real-stock cafe demo creation, H.264/AAC export,
  full MP4 decoding, source-byte preservation, and portable ZIP reimport passed.
  Both test projects were deleted through their own workspace API; the temporary
  local server was stopped.
- **Deployment:** documentation only. No application deployment or Azure
  configuration change was made.

### 2026-10-29: submission/demo audit in progress

- **Verified source:** all implementation commits currently in this repository
  are dated October 29, 2026. The published event overview lists an October 26
  kickoff and November 4, 9 PM ET submission deadline. This establishes recorded
  code dates, not participant acceptance or complete eligibility.
- **Verified live service:** the actual
  `https://foleygraph-fokas.azurewebsites.net/healthz` returned `status: ok`,
  `storage: azure_table`, and `ai_configured: true`. That is a readiness/configuration
  check, not proof of a Meta-model inference.
- **Runtime baseline:** the last deployed application source is
  `ee737d8faf24b316b692216ba8ebe82ed672b2f8`. The documentation branch changes
  no application behavior.
- **Existing artifact:** the previously verified 135.15-second production film
  and raw evidence are under `.data/showcase/final-release/` in the original
  development checkout. They show real stock edits and exports, but do not
  establish Meta-model use or WABA automation.
- **Submission gaps:** the implementation currently uses Foundry/OpenAI, not a
  demonstrated Meta model. WhatsApp Cloud API automation is not implemented,
  and no authorized WABA sender/recipient has yet been verified. The source
  repository and previously uploaded film are private, so those links are not
  yet suitable as public submission links.
- **Requirements being applied:** a film no longer than three minutes, actual
  App Service behavior, clearly identified event-built contributions, public
  source and video access, and licensed assets. Stock footage, vendor models,
  libraries, and synthetic narration must not be presented as team-built work.
- **Next safe actions:** check available Meta-model access and project-scoped
  WABA configuration without exposing secrets; implement and validate a genuine
  Meta-model contribution if feasible; audit a clean public source release;
  record/review the actual deployed scenario; then verify public video/source
  links without authentication. Do not present simulated messages as delivered
  WABA messages or claim that WhatsApp API use alone meets a Meta-model theme.
- **Submission ownership:** track selection, accepted participation, and actual
  team membership still require confirmation by the submitter. No event form
  has been submitted and no team details have been invented.

The public event overview is available at
<https://cerebralvalley.ai/e/meta-ai-developer-hackathon/hackathon/submit>.
The participant guidelines supplied for this project additionally require clear
contribution attribution and a public repository; final official eligibility
must not be inferred from this runbook.

### 2026-10-29: model/channel access audit completed

- **Evidence:** the dedicated `foleygraph-foundry` account is an `OpenAI` account.
  Its deployed models are GPT-5.4 mini, GPT-4o mini Transcribe, and GPT-4o mini TTS.
  A catalogue entry for `model-router` is not evidence that a Meta model was used.
- **WABA blocker:** no populated `WHATSAPP_`, `WABA_`, or `META_` configuration
  was found in the inspected process environment, repository `.env`, or target
  App Service settings. This does not establish that the owner has no Meta
  account elsewhere; it means no authorized live channel is available to this
  implementation yet.
- **Public-source route:** the original GitLab project remains private.
  Authenticated GitHub access for a separate, clean public submission repository
  is available. Publication is still pending source/asset review; do not make
  private project history or attachments public as a shortcut.
- **Candidate under investigation, not implemented:** Meta's publicly available
  SAM 2.1 Hiera Tiny checkpoint could provide real segmentation without a new
  hosted-model account. The official SAM 2 README explicitly licenses checkpoints
  and code under Apache 2.0. The official source revision inspected is
  `2b90b9f5ceec907a1c18123530e92e794ad901a4`.
- **Next safe action:** benchmark an isolated CPU/ONNX prototype for actual mask
  quality, latency, and memory before integrating or deploying it. This would
  use SAM 2.1 for image-anchor segmentation, not claim to run SAM 3 or the full
  SAM 2 video-memory predictor. No Meta model has been deployed or demonstrated
  by this checkpoint.

Model source and licensing:
<https://github.com/facebookresearch/sam2/tree/2b90b9f5ceec907a1c18123530e92e794ad901a4>.

### 2026-10-29: CPU Meta prototype verified, integration still pending

- **Change:** exported the official SAM 2.1 Hiera Tiny image encoder and mask
  decoder to FP32 ONNX, using the pinned Meta source above and a 768-pixel input.
  The original checkpoint SHA-256 is
  `7402e0d864fa82708a20fbd15bc84245c2f26dff0eb43a4b5b93452deb34be69`.
  This is a conversion of Meta's model, not newly trained weights.
- **Artifacts:** `.data/meta-prototype/input-768/` contains the encoder, decoder,
  mask overlays, and `runtime-verification.json`. The isolated tools use Torch
  `2.7.1`, TorchVision `0.22.1`, ONNX `1.17.0`, and ONNX Runtime `1.23.2`.
  The ordinary application environment was not used for this installation.
- **Validation:** both endpoints of the actual licensed people clip passed
  Torch/ONNX mask parity with IoU `1.0`. All five positive points per frame were
  included and all three protected points excluded. Additional positive prompts
  were sampled automatically from the existing grounded color surface to cover
  the shirt and trousers, not drawn as replacement masks. Decoder prompt counts
  `10`, `11`, and `13` executed successfully. ONNX structure checks passed, and
  neither exported graph contains a local `/Users/` path.
- **Measured limits:** a fresh, CPU-only, single-thread process on the local
  ARM Mac took about `1.73` seconds per anchor and peaked at `901.6 MiB` RSS.
  The earlier 1024-pixel prototype peaked at `1215.8 MiB`, motivating the smaller
  input. These are local prototype measurements, not B1 service performance or
  a guarantee of garment-level accuracy. Overlays were reviewed on both frames.
- **Public-source audit:** Gitleaks `8.30.1`, obtained from its checksum-verified
  official release, found zero leaks in a temporary tracked-source snapshot at
  `148870e`. The redacted report is
  `.data/submission-audit-tools/tracked-source-gitleaks.json`. This scope excludes
  private history and does not clear future changes for publication.
- **Deployment:** no Meta inference is integrated into the application yet.
  The actual App Service still runs the earlier OpenAI/CV implementation.
  No Azure configuration changed and no replacement film was recorded.
- **Next safe action:** implement an optional ONNX-only anchor-mask path, retain
  legacy project behavior, persist the exact model identity, and prove that the
  learned masks actually constrain successful renders. Validate the real clip
  locally before merging or deploying. Verify memory/readiness on the actual
  new B1 worker before filming; WhatsApp authorization remains a separate blocker.

### 2026-10-29: Meta integration in progress, motion review not yet approved

- **Code:** `feat/meta-sam2-submission` now contains the optional CPU adapter in
  `server/segmentation.py`, model preparation in `scripts/prepare_meta_model.py`,
  persisted model hashes, source-preserving rendering, and new-worker source
  fingerprint checks. These functional changes are still under local validation,
  not merged or deployed.
- **Completed checks:** the ordinary application environment installed and
  validated its declared ONNX Runtime dependencies without Torch. The checked-in
  exporter reproduced both prototype ONNX files byte-for-byte, and retained the
  official Apache 2.0 license in `LICENSES/SAM2.txt`. The last completed full
  backend run passed `55` tests. The earlier completed mutation run rejected
  `20` deliberate bugs; subsequent tracking changes still need revalidation.
- **Real-motion evidence:** a six-second, 150-frame licensed source rendered
  locally with all eight actual recorded grounding keyframes and eight real
  Meta inferences. Its combined model fingerprint is
  `842f7b7fd7c74b1bf64c80b96358f6c88ff315005300def7e6e5f6ab14d9c37c`.
  Full decoding and byte-identical source preservation passed.
- **Review finding:** endpoint images alone were insufficient. Review at one and
  two seconds exposed uncolored strips between anchor frames. Small mask holes
  were already addressed; local dense-flow propagation and bounded refreshes are
  now being tested before approving the new renderer. Evidence is under
  `.data/meta-integration-check/`; do not present earlier partial renders as the
  finished demonstration.
- **Deployment/publication:** the App Service is unchanged. The public source,
  prepared-model release, new capture, and public film are still pending.
  Until that release exists, reproduce artifacts with the export mode rather
  than assuming the prepared-bundle download URL is live.
- **Next safe action:** pass the new motion tests and mutation controls, review
  the entire real clip, update this checkpoint, then publish the feature MR and
  release only the verified result. Documentation MR !6 was already merged as
  `c1887bd`; keep all further handoff updates with the functional branch.

### 2026-10-29: complete real-stock Meta motion review passed locally

- **Change:** learned masks now use local dense flow and bounded source-color
  boundary snapping between anchors. The snapping cannot add remote components
  or freely expand a weakly supported component. Sparse controls also refresh
  the model after one second. Existing CV behavior remains unchanged.
- **Evidence:** `.data/meta-integration-check/surface-aligned-motion/` contains
  the actual six-second result, paired source/result contact sheet, project, and
  `verification.json`. All 150 frames decoded; eight genuine image-model calls
  used the complete original eight-keyframe selection. Source bytes were
  unchanged. The rightmost 140 raw image columns were identical on every frame;
  that control is not a whole-person ground-truth segmentation claim.
- **Quality review:** the earlier navy strips at one and two seconds were
  corrected. The checked source/result sequence preserves faces, the neighboring
  outfit, and the scene visually. Sampled changed-pixel coverage of the grounded
  CV surface was 99.7-100%; this is a tracking diagnostic, not measured semantic
  segmentation accuracy. A discarded coverage-triggered refresh experiment was
  slower and less reliable between grounding frames, so it is not shipped.
- **Measurements:** local render plus full decoding took `19.72` seconds, with
  `1146.8 MiB` peak process RSS on the ARM Mac. These are not B1 measurements.
- **Checks:** `37` targeted backend tests and all `23` deliberate regression
  controls pass. Python lint/format and frontend lint/format/typecheck/build pass;
  all `10` browser tests pass. Browser tests intentionally use mocked AI and do
  not substitute for the pending real Foundry HTTP scenario.
- **Deployment/publication:** still local and unmerged. The App Service and the
  previous final film are unchanged. Public source/model/video publication and
  actual B1 inference remain pending; live WABA remains unavailable/unimplemented.
- **Next safe action:** complete the real Foundry-to-Meta HTTP edit/export/import
  scenario, audit and commit this feature, publish its reviewed model bundle,
  merge through an MR, verify the actual new worker, then record the new film.

### 2026-10-29: real Foundry-to-Meta HTTP scenario and release checks passed

- **Change/verification:** the ordinary local HTTP application used the dedicated
  Foundry deployment and real Meta weights, with no mocked responses. A fresh
  people project received terracotta clothing, then a title and ambient music,
  then sage clothing while preserving the previous title/music and effect ID.
  All three revisions committed successfully. Each resulting 150-frame MP4
  decoded completely.
- **Artifacts:** `.data/meta-integration-check/live-foundry-meta-diagnostic/`
  contains the verification receipt, actual previews, finished MP4, and portable
  ZIP. Source bytes were preserved through export; importing the ZIP retained
  model provenance, edits, title, and music. The verifier deleted its two owned
  projects through the versioned API.
- **Measured local request times:** `38.31`, `24.70`, and `25.58` seconds for the
  three edits, respectively. These include real model calls and local rendering,
  not B1 performance. Backend runtime-source fingerprint:
  `ec25d71ea23a502187cdef75b879b31d280fc31b977dee83b45e8f51ec4a2f4d`.
- **Release checks:** the full backend suite passed `58` tests with one existing
  FastAPI/Starlette deprecation warning. All `23` deliberate regression controls,
  `10` browser tests, Python style, frontend style, typecheck, and build passed.
  Gitleaks found zero leaks across all `58` current tracked/nonignored source
  files; this does not audit or authorize publication of private Git history,
  runtime data, or raw authenticated traces.
- **Deployment/publication:** the feature is ready for its source MR and clean
  public snapshot, but has not yet been merged or deployed. Prepared-model
  publication, an actual B1 inference, and the new recorded film remain pending.
- **Next safe action:** publish the audited source/model release, prove the fresh
  downloader works, merge the feature MR, deploy only the existing resources,
  verify the new worker's source/model identity, then capture and critique it.

### 2026-10-29: feature MR and public Meta bundle published

- **Source:** feature commit `63eafc4` is in
  [MR !7](https://gitlab.com/fokas-labs/folio/-/merge_requests/7), not yet merged.
  The clean public repository has been created at
  <https://github.com/ShemManyu/FoleyGraph>; its audited application snapshot is
  still being prepared on a separate branch, without importing private history.
- **Model release:** the reviewed encoder, decoder, manifest, and Apache license
  are public at
  <https://github.com/ShemManyu/FoleyGraph/releases/tag/meta-sam2.1-cpu-v1>.
  GitHub-computed digests and sizes match both local reviewed ONNX files.
- **Installer correction:** the first clean anonymous download exceeded the old
  five-minute transfer budget on this connection. The installer now allows a
  bounded 15-minute transfer with visible progress. A new focused test proves a
  slow active transfer can complete while an over-budget one still fails.
  The fresh real download is being repeated; do not mark it verified yet.
- **Checks:** `60` backend tests and `24` deliberate regression controls pass.
  Runtime code/model fingerprints are unchanged from the successful real HTTP
  scenario. Earlier frontend/browser checks remain applicable.
- **CI limitation:** pipeline `3004839503` failed, not green. Backend job
  `17581812029` could not install dependencies because of `Errno 28: No space
left on device`. Frontend job `17581812030` could not pull its Node image
  because the runner's containerd disk was full. Both traces were inspected;
  no shared-runner or unrelated infrastructure was modified.
- **Deployment:** still the old runtime. Next: finish public snapshot/download
  verification, merge the approved feature, deploy the existing resources, and
  verify the actual B1 model-backed edit before recording.

### 2026-10-29: clean public source and bounded-download mirror

- **Public source:** [PR #1](https://github.com/ShemManyu/FoleyGraph/pull/1)
  contains the application tree without private Git history, local workspaces,
  model binaries, or recordings. Secret scanning of that clean history found
  no credentials. Fresh-clone instructions now use the public GitHub URL.
- **Network diagnosis:** a separate anonymous 1 MiB GitHub range request took
  `48.45s` on this connection. The second full GitHub transfer was stopped,
  not reported as successful. The same range from Azure took `2.95s`.
  These are single range measurements, not guaranteed sustained throughput.
- **Mirror:** enabled static website hosting on the already dedicated
  `foleygraphfokas1029` account and uploaded only the four reviewed model files
  under `models/meta-sam2.1-cpu-v1/`. No existing `$web` container was present.
  `allowBlobPublicAccess` remains `false`; table/project persistence is not
  exposed by enabling the separate public website endpoint.
- **Operator access:** storage website writes require Blob Data Contributor
  or management permission for Azure CLI's `--auth-mode key` lookup. The
  account key was not printed, stored in the repository, or supplied in a URL.
  Do not upload workspaces, credentials, or raw capture traces to `$web`.
- **Installer:** now uses the versioned Azure mirror by default, retaining
  the reviewed hashes, size cap, 30-second inactivity timeout, and bounded
  15-minute transfer budget.
- **Verification:** a full fresh anonymous default installation now passes.
  Neither ONNX file existed in the public checkout before the run. All four
  prepared file hashes match the reviewed local export and GitHub release
  digests. Both public range probes match the original encoder bytes.
  All `58` tracked application files match the private working tree, and both
  produce backend fingerprint
  `ec25d71ea23a502187cdef75b879b31d280fc31b977dee83b45e8f51ec4a2f4d`.
  The new mirror/installer validation also passes all `10` focused
  segmentation tests. Detailed local receipt:
  `.data/submission-audit-tools/public-model-verification.json`.
- **CI:** functional pipeline `3004913448` also failed because of runner disk
  exhaustion, confirmed in backend job `17582405560` and frontend job
  `17582405561`. This is not a successful CI run.
- **Next:** merge the source PR/MR, deploy, and measure a real B1 edit.

### 2026-10-29: public main, deployed model, and first B1 deadline failure

- **Published:** public application [PR #1](https://github.com/ShemManyu/FoleyGraph/pull/1)
  is merged as `850643f`. A credential-free HTTPS clone of public main succeeded;
  all `58` tracked files matched the private source and backend fingerprint.
  Private feature [MR !7](https://gitlab.com/fokas-labs/folio/-/merge_requests/7)
  is merged as `5a2e7a6`, without bypassing a required branch check.
- **Deployed:** Azure build `3f47a73b-db60-4e5f-a28a-d5b159f7496f` completed.
  HTTPS, Table Storage, frontend HTML, backend `ec25d71e...`, and model
  `842f7b7f...` passed the source-aware readiness check. The plan remains
  B1 with one instance.
- **Actual B1 result:** the first full six-second outfit edit returned HTTP
  `422`: `This color edit took too long. Try a shorter clip.` The request took
  `165.84s`, including grounding. Readiness did not prove successful inference.
  No successful production Meta demo is claimed. The raw failed take is retained
  separately under `.data/showcase/meta-submission-attempt1-timeout/`.
- **Measured memory:** Azure's one-minute maximum working-set observations reached
  about `772 MiB` around the attempt, not an exact process peak. The returned
  error identifies the render deadline, not an out-of-memory crash.
- **Rejected experiment:** four model calls instead of eight reduced the local
  render to `12.51s`, and its unit/mutation checks passed, but motion review
  exposed uncolored strips on newly revealed trousers. Sampled changed-pixel
  coverage of the CV guide fell to `88-90%`. This was visibly unacceptable and
  was discarded, not deployed. The original anchor cadence remains intact.
- **Next candidate:** reproduce the official checkpoint at a 512-pixel encoder
  input, retaining all eight actual grounding refreshes and the unchanged
  120-second render budget. Verify masks, exact provenance, reproducibility,
  and real B1 behavior before filming. Only a successful real take will enter
  the final film.

### 2026-10-29: genuine 512-pixel CPU bundle verified locally

- **Model:** the checked-in exporter reproduces the reviewed 512-pixel encoder
  and decoder byte-for-byte from the same official checkpoint and pinned Meta
  source. The v2 identity is
  `d36e9d0c438cc2278b1d32de89ccaf4352ea44d8cc9339f610bc3ced4b7d0a9a`.
  The original 768-pixel v1 files are not overwritten on either public host.
- **Independent parity:** PyTorch and ONNX masks have IoU `1.0` on both original
  endpoint controls. Variable prompt counts `6`, `7`, and `9` execute correctly;
  foreground points are covered and protected points remain outside the mask.
  Predicted quality is not measured semantic segmentation accuracy.
- **Actual runtime:** all `150` stock frames decode, with all `8` grounding
  refreshes retained. The default-runtime render and decode took `11.73s`
  locally and peaked at about `749 MiB` RSS. This is a local ARM measurement,
  not B1 performance. Sampled CV-guide changed-pixel coverage is `99.8-100%`,
  source bytes are unchanged, and the rightmost 140 raw image columns remain
  untouched on every frame. Motion contact-sheet review passed.
- **Compatibility:** image tensors, prompts, and refinement scale use the
  installed manifest's 512- or 768-pixel input. Old effect fingerprints are
  retained, not relabeled as v2. No grounding anchors, confidence/protection
  checks, atomic commit behavior, or render deadline were relaxed.
- **Checks:** `62` backend tests and `25` deliberate regression controls pass,
  including a mutation that uses the wrong installed-bundle resolution.
  Python style checks pass; frontend/browser results remain applicable because
  no frontend code or dependency changed.
- **Artifacts:** local receipts are in
  `.data/meta-integration-check/b1-512-runtime-provenance.json`,
  `.data/meta-integration-check/b1-512-default-runtime/`, and
  `.data/meta-prototype/input-512/runtime-verification.json`.
  The four reviewed files are uploaded to the versioned public Azure v2 path.
- **Next:** publish the v2 release/source, verify its anonymous installer,
  deploy to the existing B1 service, and verify an actual successful edit
  before using any replacement capture.

### 2026-10-29: v2 published and deployed, full B1 render still blocked

- **Published:** private [MR !8](https://gitlab.com/fokas-labs/folio/-/merge_requests/8)
  merged as `ae2a08f`; public [PR #2](https://github.com/ShemManyu/FoleyGraph/pull/2)
  merged as `e38d6b4`. Public model release
  <https://github.com/ShemManyu/FoleyGraph/releases/tag/meta-sam2.1-cpu-v2>
  is complete. Another full fresh anonymous default download passed, and all
  four prepared hashes match GitHub's computed release digests and the local
  reproducible export. Public main was fetched without credentials and all
  `58` tracked files matched.
- **CI:** pipeline `3005127924` failed in backend job `17584124734` with verified
  runner disk exhaustion. It is not a green pipeline.
- **Deployed:** build `160248c6-8129-4700-bc7a-43240c1fd0d9` passed readiness with
  backend `81bd2e85...` and 512-pixel model `d36e9d0c...`, on the same single B1
  instance.
- **Actual result:** the second real production take still returned the render
  deadline error, after `144.77s` including grounding. Its source is exactly the
  reviewed `6s`, `25fps`, `540x960` clip, with source hash `f77e9c8e...`.
  This is not a successful demo. The failed take is preserved separately.
- **Diagnosis:** an authorized container-side CPU probe confirms the actual
  Linux runtime uses the correct model. Import and session initialization took
  about `8.10s`; individual encoder calls took about `6-7s`, while decoder calls
  took about `0.15s`. This narrows the issue to the full render path rather than
  simply claiming missing weights or successful inference from `/healthz`.
  The first full render profile was interrupted by the diagnostic tunnel's
  expiry, so its partial output is not treated as a completed benchmark.
- **Next:** finish a bounded full-render profile on the actual container,
  distinguish compute from persistent-media I/O, fix the measured bottleneck,
  then repeat the real app scenario. Do not relax quality or publish a relabeled
  old CV recording as the new Meta demo.

### 2026-10-29: actual-container render profile completed, bounded fix in progress

- **Measured:** a complete diagnostic on the actual B1 container reached only
  `112/150` frames at `121.14s`, ending at the unchanged 120-second deadline.
  Six model predictions consumed `55.66s` in total. The diagnostic used
  container-local temporary media, so persistent customer-media storage alone
  does not explain the failure. The completed report is retained privately at
  `.data/meta-integration-check/production-b1-render-profile-v2.log`.
- **Rejected hypothesis:** a real 150-frame decode/encode comparison took
  `16.78s` with existing FFmpeg options and `15.42s` with bounded filter threads.
  Child CPU times were essentially unchanged. This is not sufficient evidence
  for an FFmpeg threading fix, and none is being shipped.
- **Candidate:** retain every grounding refresh and decoder/protection check,
  but reuse encoder features for up to eight identical resized original frames.
  Cache keys include pixels, installed input size, and model identity; masks and
  prompts are never cached. Permit Meta renders up to `180s` based on the
  measured workload, retaining the existing `120s` budget for CV-only edits.
  This still needs focused tests, deliberate regression controls, local motion
  review, and a completed actual-container candidate run.
- **Capture:** both failed takes remain private and preserved, including
  `.data/showcase/meta-submission-attempt2-512-timeout/`. No replacement film or
  successful production Meta edit is claimed.

### 2026-10-29: CPU candidate completes, deeper motion review rejects the old tracker

- **CPU result:** the isolated actual-container candidate completed all `150`
  frames with all `8` mask/decoder calls. The instrumented cold run took
  `185.16s`, including writer finalization after the last deadline check; a fresh
  render with the same source encodings cached took `74.53s`. All eight encoder
  lookups hit on the second run. Peak RSS of this diagnostic process was about
  `435 MiB`, not the combined application/container peak.
- **Local checks:** the cache and budget changes passed `66` backend tests,
  `28` deliberate regression controls, and Python style checks. Both actual B1
  output files fully decode and are byte-identical.
- **Review failure:** checking additional intermediate frames exposed uncolored
  bands at frames `10` and `62`, identically on the Mac and B1. The earlier seven
  sampled frames missed this. The strengthened every-frame check now fails
  honestly, with a worst CV-guide changed fraction of only `66.8%`. These
  renders are rejected for the final film despite completing successfully.
- **Cause and next fix:** the tracked clothing mask carries a moving hand's old
  exclusion into newly revealed fabric. A fabric-only envelope derived from the
  learned silhouette will bridge these temporary occlusions, still gated by
  current source-color components, protected points, and the learned spatial
  bounds. Object-mask holes remain untouched. Re-run every-frame coverage and
  visual review, then verify the updated actual-container output before release.
  No production edit or submission movie is claimed yet.

### 2026-10-29: every-frame fabric disocclusion verified locally

- **Fixed:** maintain a fabric-only convex envelope of learned support after
  each flow step, not just at an inference anchor. This prevents a moving hand
  from carrying an old exclusion into newly revealed garment pixels. Current
  color components, grounding and protected points remain final gates. Object
  holes and learned spatial limits remain protected by focused tests.
- **Full motion:** the strengthened verifier checks all `150` frames, not seven
  samples. Its minimum CV-guide changed fraction is now `99.97%`, with all `8`
  model/decoder calls retained. Original source bytes and the rightmost 140 raw
  columns remain unchanged on every frame. The nine-frame contact sheet,
  including the previously failing frames `10` and `62`, passed visual review.
  The local render/decode plus verification took `11.92s`; this is not B1 timing.
- **Cache:** new previews use a new namespace so patchy old renders are not
  mistaken for the corrected output. Existing projects/history are not rewritten.
- **Next:** verify the same updated code in an isolated actual-container run,
  publish the checked source through PR/MR, deploy, and test the real HTTP journey.
  The live service still runs the earlier source until that deployment succeeds.

### 2026-10-29: corrected motion passes every-frame checks on the actual B1 CPU

- **Actual container:** an isolated process using the candidate source completed
  the real six-second clip in `154.10s`, including full decode and every-frame
  diagnostic checks. All `150` frames and all `8` model/decoder calls were
  retained. Minimum CV-guide changed fraction was `99.99%`; the original source
  and rightmost 140 raw columns remained unchanged on every frame.
- **Review:** the corrected nine-frame real-container contact sheet includes
  the previously failing motion, and the complete exported clip is retained for
  review at `.data/meta-integration-check/production-b1-disocclusion-check/`.
  This is actual B1 inference, but still not a production HTTP edit.
- **Checks:** `68` backend tests, `30` deliberate regression controls, Python
  lint and format checks pass. Controls reject lost encoder reuse, wrong model
  cache identity, the old deadline, retained occlusion holes, and accidentally
  filling object-mask holes. No frontend or dependency changed.
- **Capacity:** diagnostic process peak RSS was about `456 MiB`, not an
  aggregate container peak. The plan remains one B1 instance; no paid scaling,
  dropped anchors or lower-resolution model was required.
- **Next:** publish this verified source, deploy it, and record a new real HTTP
  journey with exact backend/model guards. Only that successful capture will
  establish the production scenario and enter the final movie.

### 2026-10-29: verified CPU/motion source published, deployment underway

- **Merged:** private [MR !9](https://gitlab.com/fokas-labs/folio/-/merge_requests/9)
  is merged as `110c68c`; public
  [PR #3](https://github.com/ShemManyu/FoleyGraph/pull/3) is merged as `a88816b`.
  A credential-free fetch of public main succeeded and all `58` tracked files
  matched. The new public commit's credential scan found no leaks.
- **CI:** pipeline `3005396345` is failed, not green. Backend job `17586338706`
  exhausted runner disk during dependency installation; frontend job
  `17586338707` exhausted disk while pulling the Node image. The unchanged
  project merge policy does not require successful CI; no protection was
  disabled or bypassed. The local `68` tests and `30` deliberate controls passed.
- **Deployment:** the existing-resource release command is running, using
  backend fingerprint
  `bd45977590bfe3c3f2742030a935f709d8ed8256dfded06f288c5e19d13d3859`
  and the unchanged verified v2 model. Production readiness and the full HTTP
  scenario remain unverified until the build and new capture complete.
- **Cleanup:** the temporary SSH tunnel is stopped. Only the inspected,
  task-owned diagnostic files and directory were removed from the container;
  verified receipts, outputs and both failed takes remain private locally.

### 2026-10-29: corrected source deployed and exact runtime readiness verified

- **Deployed:** Azure build `ef06d5d8-fba4-45c4-b432-ca74f3f5361e` completed.
  HTTPS, frontend, Table Storage, backend `bd459775...` and model `d36e9d0c...`
  passed readiness. A separate public health/config check confirmed those exact
  identities. The plan is still B1 with one instance.
- **Next:** record the complete real browser journey in a fresh
  `.data/showcase/meta-submission/` directory, checking source/model identities
  before starting. Readiness is not a successful edit; the actual chat requests,
  revisions and exports must still complete before a production demo is claimed.

### 2026-10-29: third actual HTTP take still reaches the deadline

- **Actual result:** the cold production request returned HTTP `422` after
  `230.19s`, including planning/grounding, with the Meta render deadline message.
  Correct source/model readiness and the isolated container's local-scratch
  result did not establish the end-to-end production path.
- **Preserved:** this failed take is retained separately as
  `.data/showcase/meta-submission-attempt3-cache-budget-timeout/`. It will not be
  used in the final film. The private workspace state was saved with restrictive
  permissions so this owned test project can be inspected/cleaned without
  touching another user's workspace.
- **Next:** compare encoding to persistent `/home` storage against local
  temporary storage on the same container. The earlier codec comparison used
  local output only and cannot rule out persistent-write latency. Do not mask
  the failure by recording only a warmed retry or claiming a finished demo.

### 2026-10-29: persistent-write hypothesis rejected, asynchronous edit path needed

- **Measured:** the same 150-frame decode/encode took `19.26s` on local `/tmp`
  and `18.30s` on persistent `/home/foleygraph/temporary`. Child CPU was about
  `12.5s` in either case; the persistent source copy took `0.12s`. This does not
  justify an I/O rewrite. The temporary diagnostic directories and tunnel are
  cleaned up.
- **Next implementation:** return a real accepted-job response for chat edits
  and let the existing browser poll for completion, rather than holding one HTTP
  request through unpredictable CPU work. Keep the same single processing slot,
  workspace isolation, atomic revision commits, and App Service/Table Storage
  architecture. Bound Meta processing to five minutes instead of the inadequate
  three-minute budget; UI/API callers must not present acceptance as success.
  Keep job receipts bounded and process-local, explicitly document interruption
  on worker restart, and retain durable completed project revisions in Table
  Storage. Verify success, late failure, isolation and conflicts before release.

### 2026-10-29: bounded background chat workflow implemented, validation underway

- **Implemented on `fix/async-chat-edits`:** optional `Prefer: respond-async`
  acceptance, private receipt polling, a single reserved processing permit,
  bounded 64-result retention and safe late errors. Existing synchronous callers
  retain their response shape. The browser waits for the actual result, not the
  accepted response, and allows ten minutes for the whole edit.
- **Preserved:** source pixels, tracking/mask cadence, revision checks and the
  render-before-commit transaction are unchanged. Meta processing now allows
  300 seconds; CV remains 120. No new dependency, service, worker or SKU.
- **Tests being run:** forced processing gates distinguish genuine acceptance
  from completion; checks cover workspace isolation, admission, failure without
  revision changes, permit release, conflict protection and receipt loss after
  restart. Browser checks cover polling and late failure. Local results and
  cold production success have not yet been claimed.

### 2026-10-29: background edits verified locally, release pending

- **Passed:** `74` backend tests, `33` deliberate regression controls, Python
  lint/format, frontend lint/format/typecheck/build, and all `10` browser
  scenarios. Processing-gate tests and the mutated controls prove that another
  workspace cannot inspect a receipt and that failure releases admission.
- **Actual local HTTP:** one Uvicorn worker returned `202` in `0.0019s` while
  the controlled worker remained blocked. The submitting TCP connection was
  closed, then a different connection in the same workspace observed real
  completion after `2.10s`. Foreign receipt lookup was `404`, concurrent heavy
  work was `429`, a late failure preserved the revision, and a retry completed.
  This used a deterministic gated director to test transport, not live Foundry
  or production model evidence. The owned server and temporary media were
  removed. Receipt: `.data/meta-integration-check/async-http-verification.json`.
- **Browser correction:** the initial 12-case run reached the real shared-IP
  processing quota during its last export. The polling checks now reuse the
  existing mobile-chat and failure scenarios instead of creating extra demo
  projects. All 10 pass without changing or disabling production rate limits.
- **Next:** publish the exact source through PR/MR, verify deployment readiness,
  and record a fresh cold production take. The recorder now observes the actual
  accepted response and the browser's terminal poll, rather than expecting an
  immediate `200`. No production edit or finished replacement movie is claimed
  by these local checks.

### 2026-10-29: asynchronous source published, exact deployment next

- **Merged:** private MR
  [!10](https://gitlab.com/fokas-labs/folio/-/merge_requests/10) at
  `f35581448fea69ea79e237e2ed652180ccf75bd0`; public PR
  [#4](https://github.com/ShemManyu/FoleyGraph/pull/4) at
  `ee197719f02323215854e8a81d7e010ace966e44`. The public snapshot passed the
  new-commit credential scan. A fresh HTTPS fetch with an empty credential
  environment verified public-main access and exact parity for all 58 files.
- **CI limitation:** pipeline `3005523756` is not green. Frontend job
  `17587339522` failed from verified runner disk exhaustion before tests;
  backend job `17587339521` remained running after the bounded wait. The
  project has `only_allow_merge_if_pipeline_succeeds=false`; no protection
  was disabled. The completed local checks above are the verification evidence.
- **Release identity:** backend fingerprint
  `9255c4741a9cda693380bba29138a5925b88427389d9fc7a886aa60f40d6afa9`;
  unchanged reviewed 512-pixel model fingerprint
  `d36e9d0c438cc2278b1d32de89ccaf4352ea44d8cc9339f610bc3ced4b7d0a9a`.
  The rebuilt frontend contains job polling. Deploy the merged source and
  verify all identities before the fresh cold take. Publication is not yet
  production render success.

### 2026-10-29: asynchronous build deployed, fresh live capture starting

- **Deployed:** Azure build `8583f86a-d4a5-44e5-b9c0-d55a02bdc003`, using
  the existing-resource release without provisioning or configuration changes.
  Exact backend fingerprint `9255c474...`, rebuilt HTML/assets, Table Storage
  access, Foundry availability and the reviewed `d36e9d0c...` 512-pixel model
  passed readiness. Receipt:
  `.data/meta-integration-check/production-async-readiness.json`.
- **Not prewarmed:** readiness inspected health and model metadata only, without
  running inference. A fresh capture directory is available. The recorder also
  verifies the runtime inside each browser's own session and saves private
  workspace state with restrictive permissions.
- **Next:** actual accepted edit, terminal poll, retained title/music, real
  MP4 download and scoped cafe sound comparison. Readiness alone still does not
  establish a working Meta recolor or a finished movie.

### 2026-10-29: first live async response clarified instead of rendering

- The real browser received `202` in `0.29s` and a completed job after `8.16s`,
  but Foundry returned a shade question, not actions. The project remained at
  revision zero. The recorder correctly rejected this as an applied-edit take.
  This verifies live acceptance/polling, **not Meta render completion**.
- Preserve the take as
  `.data/showcase/meta-submission-attempt4-async-clarification/`. No Meta
  inference ran through this clarification path. Retry with the more explicit
  garment request used by the narration, `Make the left man's clothes
  terracotta.`, without fabricating a result or warming the encoder first.
  Unnecessary model clarification remains a known nondeterministic limitation.

### 2026-10-29: actual production Meta journey and exports completed

- **Actual App Service:** the explicit garment request completed with saved
  Meta provenance at revision 1. Adding the title and ambient music produced
  revision 2; sage-green revision 3 retained the same effect identity, title and
  music. Each request used real `202` acceptance and the browser's real terminal
  poll. The first recolor was not prewarmed by a diagnostic inference.
- **Measured complete waits:** first color `163.53s`, title/music `110.59s`,
  follow-up color `90.85s`, finished-reel export `4.37s`. These are slow B1 CPU
  edits, not instant editing. The successful scenario uses more explicit wording
  than the earlier timed-out takes; it does not prove a universal latency bound.
- **Captured:** `.data/showcase/meta-submission/` contains the real mobile-sized
  browser/audio recordings, downloaded MP4s and private editable bundles.
  Capture-only checks fully decoded all three finished exports, verified
  unchanged source hashes, and measured the pour at `-3.00 dB`. Room and ceramic
  WAV layers are byte-identical before/after. There were no browser errors.
- **Next:** review motion against the actual saved geometry, compose the
  three-minute film, verify its final mixed narration/captions and publish only
  curated, credential-free artifacts. A public playable film is still pending.

### 2026-10-29: assembled film withheld after crop-edge motion review

- The composed film is `164.39s`, 1080p H.264/AAC, fully decodable, with zero
  clipped samples. ASR of its actual final mix matched narration at `0.9842`;
  captions match the script, in at most two lines and 42 characters per line.
  **It is not published yet.**
- Reviewing all 150 recorded frames, not just the contact-sheet samples,
  exposed a short original-color band at the bottom crop boundary in frames
  6 and 7. The worst recorded coverage of the local visible source-color guide
  was `96.80%`, below the diagnostic's `98%` gate. The local raw rerender's
  `99.97%` result did not establish the recorded Linux output. These are guide
  comparisons, not semantic segmentation accuracy.
- The discrepancy image localizes the largest region to the bottom 22 pixels,
  not a moving hand. Dense flow currently samples outside the prior frame as
  zero, deleting offscreen continuation of a still-visible garment. Fix this
  boundary condition, retain source/protection gates and object holes, then
  require a fresh real recording. Do not hide the band by trimming those frames
  or relaxing the gate. Evidence is under
  `.data/showcase/meta-submission/review/early-frame-discrepancy.*`.

### 2026-10-29: crop-edge cause located, grounded tracking correction

- **Rejected hypothesis:** zero-border sampling was not the observed cause.
  The isolated B1 old/replicated-border renders processed all 150 frames
  with eight Meta calls and unchanged source bytes, reaching 99.9899% minimum
  tracked-guide coverage. Both nevertheless reproduce the blue strip, with
  pixels **identical** to the real recording at frames 6 and 7. The misleading
  raw metric excluded the missing fabric because it used the drifting polygon.
  The speculative border change and its tests were withdrawn.
- **Cause:** the grounded polygon explicitly reaches the bottom crop edge, but
  its affine motion estimate follows shirt movement inward. The connected-color
  guide then clips still-visible trouser fabric. This is a crop-edge grounding
  problem, not an HTTP, model-quality or codec problem.
- **New regression:** four deterministic rotated cases exercise real garment
  recoloring with an inward tracking estimate. All fail before the correction
  and also require all other pixels, including another same-color garment, to
  remain unchanged afterward.
- **Correction on `fix/edge-mask-propagation`:** preserve explicitly grounded
  fabric crop vertices during affine tracking. Other surfaces and downstream
  source/Meta/protection gates are unchanged. Cache namespace is `surface-v18`.
  No new model, dependency or resource. Verification and a fresh recorded take
  are required; the earlier movie remains unpublished.
- **Local verification passed:** 78 backend cases, Python lint/format and all 34
  deliberate regression controls. Removing crop-edge preservation makes the
  four new cases fail. Frontend source/build is unchanged. Candidate runtime
  fingerprint: `9248d6e6ceedba551fadce398d182de3dc322d2d8d502e37a926ec9f7ad713a5`.
- **Verification corrected:** compare against the original interpolated grounding
  polygon, not the propagated polygon being tested. This strengthens the same
  98% diagnostic threshold and exposes the actual omitted cloth. The diagnostic
  process is separate from the serving worker; owned remote files and the first
  tunnel were removed/stopped.
- **Publication gate strengthened:** both the first recolor and final color
  revision must supply 150-frame recorded-video checks bound to their exact
  MP4 and saved project bytes. Captions are applied to both comparison baselines,
  never altered in the recording. The older movie was explicitly rejected
  despite its passing decode/audio checks. These are source-guide diagnostics,
  not semantic segmentation accuracy.

### 2026-10-29: exact production crop defect reproduced and corrected on B1

- **Negative control now catches the real defect:** using the independent
  grounding guide on the actual saved production geometry, old code reaches
  only **96.8189%** minimum raw guide coverage across 150 frames.
- **Correction passes:** the same B1, source, model and geometry reach
  **99.9640%** with only crop-edge preservation added. Both runs use eight
  actual Meta calls and preserve source bytes. Frame 6 was visually compared:
  the old visible blue trouser strip is gone, with the other subject unchanged
  in the checked raw control region.
- **Scope:** this is an isolated native-Linux process, not replacement footage
  for the browser film or a prewarm of the serving worker. Artifacts remain in
  `.data/meta-integration-check/native-grounded-crop-edge/`; owned remote files
  were removed and the tunnel stopped. Fresh deployed-browser proof is next.
- **Review:** private MR !11 contains the correction, four before/after
  regressions, negative control, cache invalidation and this handoff. Its
  functional pipeline `3005795385` was still running when inspected, not green.
  Earlier pipeline `3005523756` had a frontend runner-system failure and a
  still-running backend job. No pipeline protections were changed.
