"""Provision and deploy the single-service Azure application using Azure CLI."""

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.config import source_revision  # noqa: E402

SUBSCRIPTION = "85041044-a067-4f83-8afd-599930e74e7d"
TENANT = "794201fa-773d-487f-8c6f-44b2df286e78"
GROUP = "Meta-Foolio"
LOCATION = "eastus2"
APP = "foleygraph-fokas"
STORAGE = "foleygraphfokas1029"
PLAN = "foleygraph-plan"
FOUNDRY = "foleygraph-foundry"
TABLE_ROLE = "0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3"
OPENAI_ROLE = "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"


def az(*arguments: str, sensitive: bool = False, allow_missing: bool = False):
    command = [
        "az",
        *arguments,
        "--subscription",
        SUBSCRIPTION,
        "--only-show-errors",
        "-o",
        "json",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        if allow_missing and any(
            marker in result.stderr
            for marker in ("ResourceNotFound", "ResourceGroupNotFound", "NotFound")
        ):
            return None
        message = "Azure app configuration failed." if sensitive else result.stderr.strip()
        raise RuntimeError(message)
    return json.loads(result.stdout) if result.stdout.strip() else None


def ensure_role(principal: str, role: str, scope: str):
    assignments = az("role", "assignment", "list", "--scope", scope)
    if any(
        item["principalId"] == principal and item["roleDefinitionId"].endswith(role)
        for item in assignments
    ):
        return
    az(
        "role",
        "assignment",
        "create",
        "--assignee-object-id",
        principal,
        "--assignee-principal-type",
        "ServicePrincipal",
        "--role",
        role,
        "--scope",
        scope,
    )


def provision():
    account = az("account", "show")
    if account["tenantId"] != TENANT:
        raise RuntimeError("The target subscription is not in the expected tenant.")
    if not az("group", "show", "--name", GROUP, allow_missing=True):
        az("group", "create", "--name", GROUP, "--location", LOCATION)
    if not az(
        "storage",
        "account",
        "show",
        "--name",
        STORAGE,
        "--resource-group",
        GROUP,
        allow_missing=True,
    ):
        az(
            "storage",
            "account",
            "create",
            "--name",
            STORAGE,
            "--resource-group",
            GROUP,
            "--location",
            LOCATION,
            "--sku",
            "Standard_LRS",
            "--kind",
            "StorageV2",
            "--https-only",
            "true",
            "--min-tls-version",
            "TLS1_2",
            "--allow-blob-public-access",
            "false",
        )
    az("storage", "table", "create", "--name", "foleygraph", "--account-name", STORAGE)
    if not az(
        "appservice", "plan", "show", "--name", PLAN, "--resource-group", GROUP, allow_missing=True
    ):
        az(
            "appservice",
            "plan",
            "create",
            "--name",
            PLAN,
            "--resource-group",
            GROUP,
            "--location",
            LOCATION,
            "--sku",
            "B1",
            "--is-linux",
            "--number-of-workers",
            "1",
        )
    app = az("webapp", "show", "--name", APP, "--resource-group", GROUP, allow_missing=True)
    if not app:
        app = az(
            "webapp",
            "create",
            "--name",
            APP,
            "--resource-group",
            GROUP,
            "--plan",
            PLAN,
            "--runtime",
            "PYTHON:3.12",
            "--assign-identity",
            "[system]",
            "--https-only",
            "true",
        )
    if not app.get("identity", {}).get("principalId"):
        az("webapp", "identity", "assign", "--name", APP, "--resource-group", GROUP)
        app = az("webapp", "show", "--name", APP, "--resource-group", GROUP)
    foundry = az(
        "cognitiveservices",
        "account",
        "show",
        "--name",
        FOUNDRY,
        "--resource-group",
        GROUP,
        allow_missing=True,
    )
    if not foundry:
        foundry = az(
            "cognitiveservices",
            "account",
            "create",
            "--name",
            FOUNDRY,
            "--resource-group",
            GROUP,
            "--location",
            LOCATION,
            "--kind",
            "OpenAI",
            "--sku",
            "S0",
            "--custom-domain",
            "foleygraph-fokas-ai",
        )
    deployments = az(
        "cognitiveservices",
        "account",
        "deployment",
        "list",
        "--name",
        FOUNDRY,
        "--resource-group",
        GROUP,
    )
    for name, model, version, capacity in (
        ("foleygraph-director", "gpt-5.4-mini", "2026-03-17", "80"),
        ("foleygraph-transcribe", "gpt-4o-mini-transcribe", "2025-12-15", "1"),
    ):
        if not any(item["name"] == name for item in deployments):
            az(
                "cognitiveservices",
                "account",
                "deployment",
                "create",
                "--name",
                FOUNDRY,
                "--resource-group",
                GROUP,
                "--deployment-name",
                name,
                "--model-name",
                model,
                "--model-version",
                version,
                "--model-format",
                "OpenAI",
                "--sku-name",
                "GlobalStandard",
                "--sku-capacity",
                capacity,
            )
    principal = app["identity"]["principalId"]
    resource_root = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{GROUP}/providers"
    ensure_role(
        principal, TABLE_ROLE, f"{resource_root}/Microsoft.Storage/storageAccounts/{STORAGE}"
    )
    ensure_role(
        principal, OPENAI_ROLE, f"{resource_root}/Microsoft.CognitiveServices/accounts/{FOUNDRY}"
    )
    return foundry["properties"]["endpoint"]


def configure(endpoint: str):
    existing = az(
        "webapp",
        "config",
        "appsettings",
        "list",
        "--name",
        APP,
        "--resource-group",
        GROUP,
        sensitive=True,
    )
    current = {item["name"]: item["value"] for item in existing}
    settings = {
        "AZURE_STORAGE_ACCOUNT": STORAGE,
        "AZURE_STORAGE_TABLE": "foleygraph",
        "AZURE_OPENAI_ENDPOINT": endpoint,
        "AZURE_OPENAI_DEPLOYMENT": "foleygraph-director",
        "AZURE_OPENAI_TRANSCRIPTION_DEPLOYMENT": "foleygraph-transcribe",
        "WORKSPACE_SECRET": current.get("WORKSPACE_SECRET") or secrets.token_urlsafe(48),
        "FOLEYGRAPH_DATA_DIR": "/home/foleygraph",
        "WEBSITES_ENABLE_APP_SERVICE_STORAGE": "true",
        "SCM_DO_BUILD_DURING_DEPLOYMENT": "true",
        "ENABLE_ORYX_BUILD": "true",
        "WEBSITES_CONTAINER_START_TIME_LIMIT": "600",
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    with tempfile.TemporaryDirectory(prefix="foleygraph-config-") as directory:
        path = Path(directory) / "settings.json"
        path.touch(mode=0o600)
        path.write_text(json.dumps(settings), encoding="utf-8")
        az(
            "webapp",
            "config",
            "appsettings",
            "set",
            "--name",
            APP,
            "--resource-group",
            GROUP,
            "--settings",
            f"@{path}",
            sensitive=True,
        )
    az(
        "webapp",
        "config",
        "set",
        "--name",
        APP,
        "--resource-group",
        GROUP,
        "--startup-file",
        "bash startup.sh",
        "--always-on",
        "true",
        "--http20-enabled",
        "true",
        "--ftps-state",
        "Disabled",
        "--min-tls-version",
        "1.2",
        "--generic-configurations",
        '{"healthCheckPath":"/healthz"}',
    )
    az("webapp", "update", "--name", APP, "--resource-group", GROUP, "--https-only", "true")


def package(path: Path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ("requirements.txt", "requirements.lock", "startup.sh"):
            archive.write(ROOT / name, name)
        for file in sorted((ROOT / "server").glob("*.py")):
            archive.write(file, file.relative_to(ROOT))
        for file in sorted((ROOT / "server" / "assets").rglob("*")):
            if file.is_file():
                archive.write(file, file.relative_to(ROOT))
        for file in sorted((ROOT / "web" / "dist").rglob("*")):
            if file.is_file():
                archive.write(file, file.relative_to(ROOT))


def readiness(url: str):
    expected_revision = source_revision(ROOT)
    manifest = ROOT / "server" / "assets" / "models" / "sam2.1-hiera-tiny" / "manifest.json"
    expected_model = json.loads(manifest.read_text())["files"] if manifest.is_file() else None
    expected_model_hash = (
        hashlib.sha256(
            json.dumps(expected_model, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if expected_model
        else None
    )
    deadline = time.monotonic() + 420
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/healthz", timeout=15) as response:
                status = json.load(response)
            with urllib.request.urlopen(url, timeout=15) as response:
                html = response.read().decode()
            if (
                status.get("status") == "ok"
                and status.get("storage") == "azure_table"
                and status.get("ai_configured")
                and status.get("backend_revision") == expected_revision
                and html == (ROOT / "web" / "dist" / "index.html").read_text(encoding="utf-8")
            ):
                with urllib.request.urlopen(f"{url}/api/config", timeout=15) as response:
                    configuration = json.load(response)
                actual_model_hash = (configuration.get("mask_model") or {}).get("sha256")
                if actual_model_hash == expected_model_hash:
                    return
        except (urllib.error.URLError, TimeoutError, ValueError):
            pass
        time.sleep(10)
    raise RuntimeError(
        "Deployment was submitted, but readiness did not become healthy. Inspect App Service logs."
    )


def deployment_complete(deployment_id: str):
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        deployments = az(
            "webapp",
            "log",
            "deployment",
            "list",
            "--name",
            APP,
            "--resource-group",
            GROUP,
        )
        deployment = next((item for item in deployments if item["id"] == deployment_id), None)
        if deployment and deployment.get("complete"):
            if deployment["status"] != 4:
                raise RuntimeError(
                    f"Azure deployment {deployment_id} failed. Inspect its build logs."
                )
            return
        time.sleep(10)
    raise RuntimeError(f"Azure deployment {deployment_id} is still building. Check its build logs.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-build", action="store_true", help="Use an already verified web/dist build."
    )
    parser.add_argument(
        "--skip-provision", action="store_true", help="Deploy to the existing configured resources."
    )
    args = parser.parse_args()
    os.chdir(ROOT)
    if not args.skip_build:
        if not (ROOT / "web" / "node_modules").is_dir():
            subprocess.run(["npm", "--prefix", "web", "ci"], check=True)
        subprocess.run(["npm", "--prefix", "web", "run", "build"], check=True)
    if not (ROOT / "web" / "dist" / "index.html").is_file():
        raise RuntimeError("Build the frontend before packaging the deployment.")
    if not args.skip_provision:
        print(f"Provisioning App Service, Table Storage, and Foundry in {GROUP}.", flush=True)
        endpoint = provision()
        configure(endpoint)
    print("Deploying the verified application package.", flush=True)
    with tempfile.TemporaryDirectory(prefix="foleygraph-deploy-") as directory:
        archive = Path(directory) / "application.zip"
        package(archive)
        result = az(
            "webapp",
            "deploy",
            "--name",
            APP,
            "--resource-group",
            GROUP,
            "--type",
            "zip",
            "--src-path",
            str(archive),
            "--clean",
            "true",
            "--track-status",
            "false",
            "--async",
            "true",
            "--timeout",
            "600000",
        )
    deployment_id = result.get("id") or result.get("deploymentId")
    if not deployment_id:
        raise RuntimeError("Azure accepted the package but did not return a deployment ID.")
    print(f"Waiting for Azure build {deployment_id}.", flush=True)
    deployment_complete(deployment_id)
    url = f"https://{APP}.azurewebsites.net"
    print("Checking HTTPS, application readiness, and Table Storage access.", flush=True)
    readiness(url)
    print(f"Ready: {url}", flush=True)


if __name__ == "__main__":
    main()
