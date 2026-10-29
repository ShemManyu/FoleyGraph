import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description="Run FoleyGraph locally with SQLite persistence.")
    parser.add_argument(
        "--azure", action="store_true", help="Enable the deployed Azure OpenAI models."
    )
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    environment = dict(os.environ)
    environment["AZURE_STORAGE_ACCOUNT"] = ""
    environment["FOLEYGRAPH_DATA_DIR"] = str(ROOT / ".data" / "local")
    if args.azure:
        # Keep the development credential in process memory, never in a file or command argument.
        result = subprocess.run(
            [
                "az",
                "cognitiveservices",
                "account",
                "keys",
                "list",
                "--name",
                "foleygraph-foundry",
                "--resource-group",
                "Meta-Foolio",
                "--subscription",
                "85041044-a067-4f83-8afd-599930e74e7d",
                "-o",
                "json",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        environment["AZURE_OPENAI_API_KEY"] = json.loads(result.stdout)["key1"]
        environment["AZURE_OPENAI_ENDPOINT"] = "https://foleygraph-fokas-ai.openai.azure.com/"
        environment["AZURE_OPENAI_DEPLOYMENT"] = "foleygraph-director"
        environment["AZURE_OPENAI_TRANSCRIPTION_DEPLOYMENT"] = "foleygraph-transcribe"
    os.chdir(ROOT)
    os.execve(
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "server.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.port),
        ],
        environment,
    )


if __name__ == "__main__":
    main()
