import hashlib
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def source_revision(root: Path = ROOT) -> str:
    files = sorted((root / "server").glob("*.py")) + [
        root / name for name in ("requirements.txt", "requirements.lock", "startup.sh")
    ]
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


@dataclass
class Settings:
    data_dir: Path = field(
        default_factory=lambda: Path(os.getenv("FOLEYGRAPH_DATA_DIR", ROOT / ".data")).resolve()
    )
    storage_account: str = field(default_factory=lambda: os.getenv("AZURE_STORAGE_ACCOUNT", ""))
    storage_table: str = field(
        default_factory=lambda: os.getenv("AZURE_STORAGE_TABLE", "foleygraph")
    )
    openai_endpoint: str = field(
        default_factory=lambda: os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
    )
    openai_key: str = field(default_factory=lambda: os.getenv("AZURE_OPENAI_API_KEY", ""))
    director_model: str = field(
        default_factory=lambda: os.getenv("AZURE_OPENAI_DEPLOYMENT", "foleygraph-director")
    )
    transcription_model: str = field(
        default_factory=lambda: os.getenv(
            "AZURE_OPENAI_TRANSCRIPTION_DEPLOYMENT", "foleygraph-transcribe"
        )
    )
    workspace_secret: str = field(default_factory=lambda: os.getenv("WORKSPACE_SECRET", ""))
    web_dir: Path = ROOT / "web" / "dist"
    max_duration: float = 20.0
    max_upload_bytes: int = 100 * 1024 * 1024

    def prepare(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for folder in ("media", "samples", "temporary"):
            (self.data_dir / folder).mkdir(exist_ok=True)
        if not self.workspace_secret:
            if os.getenv("WEBSITE_SITE_NAME"):
                raise RuntimeError("WORKSPACE_SECRET must be configured on App Service.")
            secret_file = self.data_dir / ".workspace-secret"
            try:
                with secret_file.open("x", encoding="ascii") as handle:
                    secret_file.chmod(0o600)
                    handle.write(secrets.token_urlsafe(48))
            except FileExistsError:
                pass
            self.workspace_secret = secret_file.read_text(encoding="ascii").strip()
