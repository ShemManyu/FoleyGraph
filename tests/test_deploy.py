import io
import json
import zipfile

import pytest

from scripts import deploy
from server.config import source_revision
from server.demo import DEMO_ASSETS


def test_runtime_package_contains_the_offline_stock_demo_and_sounds(tmp_path):
    path = tmp_path / "application.zip"
    deploy.package(path)
    with zipfile.ZipFile(path) as archive:
        for asset in DEMO_ASSETS.iterdir():
            relative = asset.relative_to(deploy.ROOT).as_posix()
            assert archive.read(relative) == asset.read_bytes()


def test_deployment_waits_for_its_own_completed_build(monkeypatch):
    previous = {"id": "previous", "status": 4, "complete": True}
    pending = {"id": "current", "status": 4, "complete": False}
    completed = {**pending, "complete": True}
    responses = iter(([previous], [previous, pending], [previous, completed]))
    waits = []
    monkeypatch.setattr(deploy, "az", lambda *args: next(responses))
    monkeypatch.setattr(deploy.time, "monotonic", iter(range(10)).__next__)
    monkeypatch.setattr(deploy.time, "sleep", waits.append)

    deploy.deployment_complete("current")

    assert waits == [10, 10]


def test_deployment_reports_its_build_failure(monkeypatch):
    monkeypatch.setattr(
        deploy,
        "az",
        lambda *args: [
            {"id": "previous", "status": 4, "complete": True},
            {"id": "current", "status": 3, "complete": True},
        ],
    )
    with pytest.raises(RuntimeError, match="deployment current failed"):
        deploy.deployment_complete("current")


def test_deployment_does_not_report_success_when_the_build_times_out(monkeypatch):
    monkeypatch.setattr(
        deploy,
        "az",
        lambda *args: [{"id": "previous", "status": 4, "complete": True}],
    )
    monkeypatch.setattr(deploy.time, "monotonic", iter((0, 1, 601)).__next__)
    monkeypatch.setattr(deploy.time, "sleep", lambda seconds: None)

    with pytest.raises(RuntimeError, match="deployment current is still building"):
        deploy.deployment_complete("current")


def test_readiness_rejects_a_healthy_old_worker_before_accepting_the_new_source(
    tmp_path, monkeypatch
):
    (tmp_path / "web" / "dist").mkdir(parents=True)
    (tmp_path / "web" / "dist" / "index.html").write_text("same frontend")
    (tmp_path / "server").mkdir()
    (tmp_path / "server" / "main.py").write_text("new backend")
    for name in ("requirements.txt", "requirements.lock", "startup.sh"):
        (tmp_path / name).write_text("")
    monkeypatch.setattr(deploy, "ROOT", tmp_path)
    revisions = iter(("previous-worker", source_revision(tmp_path)))
    waits = []

    def response(url, timeout):
        if url.endswith("/healthz"):
            return io.BytesIO(
                json.dumps(
                    {
                        "status": "ok",
                        "storage": "azure_table",
                        "ai_configured": True,
                        "backend_revision": next(revisions),
                    }
                ).encode()
            )
        if url.endswith("/api/config"):
            return io.BytesIO(b'{"mask_model":null}')
        return io.BytesIO(b"same frontend")

    monkeypatch.setattr(deploy.urllib.request, "urlopen", response)
    monkeypatch.setattr(deploy.time, "sleep", waits.append)
    monkeypatch.setattr(deploy.time, "monotonic", iter(range(10)).__next__)
    deploy.readiness("https://example.invalid")
    assert waits == [10]
