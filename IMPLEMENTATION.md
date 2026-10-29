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
| Repository access                                   | The GitLab repository is private.                                          |
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
git clone https://gitlab.com/fokas-labs/folio.git foleygraph
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

The [reviewed prepared bundle](https://github.com/ShemManyu/FoleyGraph/releases/tag/meta-sam2.1-cpu-v1)
is public. Stop the application and run:

```bash
.venv/bin/python scripts/prepare_meta_model.py
.venv/bin/python scripts/run_local.py --azure
```

Download mode verifies the two reviewed ONNX hashes, retains Meta's license,
and writes the manifest last. It needs no Torch installation or model account.
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
842f7b7fd7c74b1bf64c80b96358f6c88ff315005300def7e6e5f6ab14d9c37c
```

ONNX Runtime executes on CPU with one inference thread. SAM runs at grounding
anchors, with a one-second maximum refresh gap for sparse controls. Between
anchors, dense optical flow propagates the learned mask. Bounded source-surface
snapping repairs small disocclusions only on color components already almost
entirely supported by that mask. Original color matching and protected points
still restrict the final recolor. This is approximate hybrid tracking, not a
promise of pixel-accurate identity through occlusion.

Each inference sees immutable original pixels, not another recolor or a title.
Invalid weights, low-confidence output, missed foreground points, protected-point
violations, and unrenderable selections reject the edit. Do not silently relabel
a CV render as Meta-backed. Restart after model preparation because verified
metadata and inference sessions are cached.

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
In-flight synchronous edits can be interrupted by recycling. The health endpoint's
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

| Symptom                                             | Check or action                                                                                                                                            |
| --------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Python import/module error                          | Use `.venv/bin/python` and install the repository's requirements, not an unrelated/global environment.                                                     |
| UI missing or old                                   | Build `web/dist/` again. The backend does not serve the TypeScript source directly.                                                                        |
| Vite opens but API calls fail                       | Start the backend on port `8000`; that is the configured proxy target.                                                                                     |
| AI unavailable                                      | Set the endpoint/deployment and valid key or Entra identity. Manual mode is expected without them.                                                         |
| Foundry `401`, `403`, or deployment-not-found error | Check the correct resource, credential/RBAC access, and deployment name. Do not copy another project's key or rotate a shared resource to fix this app.    |
| Studio busy / `429`                                 | Only one heavy operation runs at a time. Wait; avoid repeated submissions. Model quota can independently cause `429`.                                      |
| Edit seems slow                                     | Visual edits in the B1 demonstration took about 77-89 seconds. Start with short clips; no instant-render guarantee is made.                                |
| Stale revision / `409`                              | Reload the latest project before resubmitting. Do not overwrite another revision blindly.                                                                  |
| Surface cannot be isolated                          | The edit is rejected rather than fabricated. Use people footage for outfit edits; pale cup/saucer separation remains difficult.                            |
| Meta model unavailable or hash mismatch             | Prepare the reviewed matching bundle, verify `/api/config`, and restart. Missing optional assets do not make an existing Meta-tagged project a CV project. |
| Missing projects after clearing cookies             | Workspaces are browser-specific. Restore a previously exported ZIP; do not delete the database or media directory.                                         |
| Microphone/native sharing unavailable               | Use HTTPS or localhost and a supporting browser/device. Desktop browsers can fall back to MP4 download.                                                    |
| Old export URL no longer works                      | Only three export directories are kept. Export again from the project.                                                                                     |
| Expected WhatsApp bot or business-data replies      | Not implemented. Sharing an MP4 is not Cloud API messaging, webhooks, or business-profile automation.                                                      |

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
