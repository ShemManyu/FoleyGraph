import shutil

import pytest
from fastapi.testclient import TestClient

from server.audio import SoundLibrary
from server.config import Settings
from server.demo import make_demo_video
from server.main import create_app
from server.models import Box, Cue, Media, Project, SceneObject
from server.storage import LocalStore
from server.studio import Studio


@pytest.fixture
def library(tmp_path):
    settings = Settings(data_dir=tmp_path, storage_account="", openai_endpoint="")
    settings.prepare()
    result = SoundLibrary(tmp_path)
    result.prepare()
    return result


@pytest.fixture
def scene():
    return Project(
        name="Two walkers and a prop",
        media=Media(duration=4, fps=24, width=640, height=360, filename="original.mp4"),
        objects=[
            SceneObject(
                id="left",
                name="Left walker",
                profile="wood",
                keyframes=[
                    Box(time=0, x=0.1, y=0.3, width=0.15, height=0.4),
                    Box(time=4, x=0.5, y=0.3, width=0.15, height=0.4),
                ],
            ),
            SceneObject(
                id="right",
                name="Right walker",
                profile="soft",
                keyframes=[Box(time=0, x=0.7, y=0.3, width=0.1, height=0.4)],
            ),
            SceneObject(id="prop", name="A little stone", profile="stone"),
        ],
        cues=[
            Cue(
                id="left-step-1",
                object_id="left",
                time=0.5,
                duration=0.26,
                asset_id="wood-footstep",
            ),
            Cue(
                id="left-step-2",
                object_id="left",
                time=1.5,
                duration=0.26,
                asset_id="wood-footstep",
            ),
            Cue(
                id="left-impact",
                object_id="left",
                kind="impact",
                time=2.3,
                duration=0.65,
                asset_id="wood-impact",
            ),
            Cue(
                id="right-step",
                object_id="right",
                time=0.8,
                duration=0.26,
                asset_id="soft-footstep",
            ),
            Cue(
                id="prop-hit",
                object_id="prop",
                kind="impact",
                time=2.2,
                duration=0.65,
                asset_id="stone-impact",
            ),
        ],
    )


@pytest.fixture
def studio(tmp_path, library, scene):
    store = LocalStore(tmp_path / "test.sqlite3")
    store.create("owner", scene)
    return Studio(store, library)


@pytest.fixture(scope="session")
def demo_video(tmp_path_factory):
    path = tmp_path_factory.mktemp("demo") / "demo.mp4"
    make_demo_video(path)
    return path


@pytest.fixture
def client(tmp_path, demo_video):
    settings = Settings(
        data_dir=tmp_path, storage_account="", openai_endpoint="", workspace_secret="test-secret"
    )
    settings.prepare()
    shutil.copyfile(demo_video, tmp_path / "demo.mp4")
    app = create_app(settings)
    with TestClient(app) as result:
        yield result
