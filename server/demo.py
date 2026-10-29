import shutil
from pathlib import Path

from server.media import probe
from server.models import COLORS, Asset, Box, Cue, Project, SceneObject

DEMO_ASSETS = Path(__file__).parent / "assets" / "demo"
DEMO_FILENAME = "morning-ritual.mp4"
STYLE_FILENAME = "weekend-style.mp4"
DEMO_SOUNDS = (
    ("demo_pour", "Velvet coffee pour", "velvet-pour", 4.0),
    ("demo_cup", "Ceramic resonance", "ceramic-drop", 0.55),
    ("demo_room", "Soft cafe air", "cafe-air", 4.0),
)


def make_demo_video(path: Path, scene: str = "coffee"):
    shutil.copyfile(DEMO_ASSETS / (STYLE_FILENAME if scene == "style" else DEMO_FILENAME), path)


def copy_demo_sounds(directory: Path, scene: str = "coffee"):
    if scene == "style":
        return
    target = directory / "assets"
    target.mkdir(parents=True)
    for asset_id, _, filename, _ in DEMO_SOUNDS:
        shutil.copyfile(DEMO_ASSETS / f"{filename}.wav", target / f"{asset_id}.wav")


def demo_project(source: Path, scene: str = "coffee") -> Project:
    if scene == "style":
        return Project(
            name="Weekend, remixed",
            brief="A real street-style clip. Keep both people and their surroundings natural.",
            media=probe(source, STYLE_FILENAME),
            source_credit="Stock video: https://www.pexels.com/video/two-men-engaging-in-conversation-outdoors-34708066/ (Pexels License: https://www.pexels.com/license/).",
            analysis_note="Licensed real stock footage, trimmed to six seconds. No illustrated or generated characters. The starting clip has no soundtrack or prepared AI edits.",
        )
    objects = [
        SceneObject(
            id="pour",
            name="Coffee pour",
            color=COLORS[0],
            profile="water",
            sound_overrides={"movement": "demo_pour"},
            keyframes=[
                Box(time=0, x=0.2, y=0.25, width=0.43, height=0.39),
                Box(time=1, x=0.2, y=0.23, width=0.4, height=0.4),
                Box(time=4.8, x=0.18, y=0.23, width=0.43, height=0.4),
                Box(time=5.6, x=0.17, y=0.13, width=0.42, height=0.28),
                Box(time=6.5, x=0.55, y=0, width=0.4, height=0.24, visible=False),
                Box(time=8, x=0.55, y=0, width=0.4, height=0.24, visible=False),
            ],
        ),
        SceneObject(
            id="cup",
            name="Ceramic cup",
            color=COLORS[1],
            profile="glass",
            sound_overrides={"impact": "demo_cup"},
            keyframes=[
                Box(time=0, x=0.18, y=0.56, width=0.55, height=0.26),
                Box(time=4, x=0.18, y=0.55, width=0.55, height=0.26),
                Box(time=8, x=0.36, y=0.55, width=0.6, height=0.27),
            ],
        ),
        SceneObject(
            id="cafe",
            name="Cafe air",
            color=COLORS[2],
            profile="soft",
            sound_overrides={"ambience": "demo_room"},
        ),
    ]
    cues = [
        Cue(
            object_id="pour",
            kind="movement",
            time=10 / 24,
            duration=3.0,
            asset_id="demo_pour",
            gain_db=-2,
            pan=-0.08,
            fade_in=0.18,
            fade_out=0.08,
        ),
        Cue(
            object_id="pour",
            kind="movement",
            time=80 / 24,
            duration=2.25,
            asset_id="demo_pour",
            gain_db=-3.5,
            pan=-0.04,
            playback_rate=0.96,
            fade_in=0.08,
            fade_out=0.25,
        ),
        Cue(
            object_id="cafe",
            kind="ambience",
            time=0,
            duration=8,
            asset_id="demo_room",
            gain_db=-15,
            pan=0,
            fade_in=0.4,
            fade_out=0.7,
        ),
    ]
    for index, frame in enumerate((16, 29, 47, 66, 83, 101, 119, 131)):
        cues.append(
            Cue(
                object_id="cup",
                kind="impact",
                time=frame / 24,
                duration=0.55,
                asset_id="demo_cup",
                gain_db=-18 - index % 3,
                pan=0.03,
                playback_rate=0.92 + index % 3 * 0.04,
            )
        )
    return Project(
        name="Slow mornings",
        brief="An intimate cafe reel. A velvety coffee pour, delicate ceramic resonance, and a quiet room. Warm, tactile, no music.",
        media=probe(source, DEMO_FILENAME),
        objects=objects,
        cues=cues,
        assets=[
            Asset(
                id=asset_id,
                name=name,
                duration=duration,
                source="Original FoleyGraph sound design, CC0-1.0",
            )
            for asset_id, name, _, duration in DEMO_SOUNDS
        ],
        source_credit="Video by WIERZBA PH: https://www.pexels.com/video/pouring-water-into-coffee-cup-14364305/ (Pexels License: https://www.pexels.com/license/). Original FoleyGraph sound design, CC0.",
        analysis_note="Prepared real stock reel with hand-authored sound layers and approximate boxes. Video by WIERZBA PH: https://www.pexels.com/video/pouring-water-into-coffee-cup-14364305/ (https://www.pexels.com/license/). Original procedural sound design: FoleyGraph / CC0. This starting sound pass is hand-authored, not an AI analysis result. Add a title through chat when you are ready.",
    )
