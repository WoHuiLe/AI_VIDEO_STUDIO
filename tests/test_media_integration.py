"""Real tiny FFmpeg jobs, not mocked subprocess success."""

import math
import shutil
import struct
import wave

import pytest
from PIL import Image

from avstudio.assets import apply_mask
from avstudio.cli import execute, parser
from avstudio.demo import create_demo
from avstudio.media import import_timeline, inspect_media
from avstudio.project import attach_audio, require_valid
from avstudio.project import register_asset
from avstudio.render import assemble, render_project
from avstudio.storage import StudioError, load_project, sha256, write_json

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                                reason="需要 FFmpeg/FFprobe 实际运行")


def tone(path, seconds=1, frequency=440):
    rate = 48000
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        stream.writeframes(b"".join(struct.pack("<h", round(2000 * math.sin(2 * math.pi * frequency * i / rate)))
                                    for i in range(round(seconds * rate))))


@pytest.fixture
def short_demo(tmp_path):
    root = tmp_path / "中文 with space and 'quote'"
    create_demo(root)
    data = load_project(root)
    data.update(width=160, height=90, fps=24)
    for shot in data["shots"]:
        shot["duration_s"] = 0.5
    write_json(root / "project.json", data)
    return root


def test_render_cache_and_silent_cut(short_demo):
    root = short_demo
    receipts = render_project(root)
    assert len(receipts) == 2 and all(not r["cached"] for r in receipts)
    old_times = [(root / r["output"]).stat().st_mtime_ns for r in receipts]
    again = render_project(root)
    assert all(r["cached"] for r in again)
    assert old_times == [(root / r["output"]).stat().st_mtime_ns for r in again]
    # Externally damaged output is detected and rebuilt, not blindly reused.
    damaged = root / receipts[0]["output"]
    damaged.write_bytes(b"invalid")
    repaired = render_project(root, shot_id="S001")[0]
    assert not repaired["cached"] and sha256(damaged) == repaired["output_sha256"]
    cut = assemble(root)
    info = cut["inspection"]["media"]
    assert [s["codec_type"] for s in info["streams"]] == ["video"]
    assert abs(float(info["format"]["duration"]) - 1) < 0.05
    assert cut["inspection"]["checks"]["full_decode"] == "PASS"


def test_audio_alignment_and_no_truncation(short_demo, tmp_path):
    root = short_demo
    audio = tmp_path / "original.wav"
    tone(audio)
    attach_audio(root, audio)
    render_project(root)
    with pytest.raises(StudioError, match="真实时间轴"):
        assemble(root)
    timings = tmp_path / "times.json"
    write_json(timings, [{"shot_id": "S001", "start_s": 0, "end_s": 0.5},
                         {"shot_id": "S002", "start_s": 0.5, "end_s": 1}])
    with pytest.raises(StudioError, match="confirmed"):
        import_timeline(root, timings)
    assert import_timeline(root, timings, True) == 2
    cut = assemble(root)
    streams = cut["inspection"]["media"]["streams"]
    assert {s["codec_type"] for s in streams} == {"video", "audio"}
    assert next(s for s in streams if s["codec_type"] == "audio")["sample_rate"] == "48000"
    # Replacing audio invalidates the old reviewed alignment.
    tone(audio, frequency=220)
    attach_audio(root, audio)
    assert all(s["timeline_status"] == "provisional" for s in load_project(root)["shots"])
    assert require_valid(root)


def test_timeline_gap_and_long_audio_are_rejected(short_demo, tmp_path):
    root = short_demo
    audio = tmp_path / "long.wav"
    tone(audio, 2)
    attach_audio(root, audio)
    timings = tmp_path / "timings.json"
    write_json(timings, [{"shot_id": "S001", "start_s": 0, "end_s": 0.5},
                         {"shot_id": "S002", "start_s": 0.6, "end_s": 1.1}])
    import_timeline(root, timings, True)
    render_project(root)
    with pytest.raises(StudioError, match="空隙"):
        assemble(root)
    write_json(timings, [{"shot_id": "S001", "start_s": 0, "end_s": 0.5},
                         {"shot_id": "S002", "start_s": 0.5, "end_s": 1}])
    import_timeline(root, timings, True)
    with pytest.raises(StudioError, match="拒绝截断"):
        assemble(root)


def test_mask_cli_preserves_png_and_original_alpha(tmp_path):
    source, mask, output = (tmp_path / n for n in ["source.png", "mask.png", "output.png"])
    Image.new("RGBA", (4, 4), (20, 30, 40, 128)).save(source)
    Image.new("L", (4, 4), 128).save(mask)
    args = parser().parse_args(["mask", str(source), str(mask), str(output)])
    execute(args)
    with Image.open(output) as result:
        assert result.getpixel((0, 0))[3] == 64
    with pytest.raises(StudioError, match="不覆盖"):
        apply_mask(source, mask, output)


def test_default_1080p_output_is_playable(short_demo):
    data = load_project(short_demo)
    data.update(width=1920, height=1080)
    data["shots"] = data["shots"][:1]
    data["shots"][0]["duration_s"] = 1 / 24
    write_json(short_demo / "project.json", data)
    receipt = render_project(short_demo)[0]
    stream = receipt["inspection"]["media"]["streams"][0]
    assert (stream["width"], stream["height"], stream["pix_fmt"]) == (1920, 1080, "yuv420p")
    assert receipt["inspection"]["checks"]["full_decode"] == "PASS"


def test_only_affected_shot_is_rebuilt(short_demo, tmp_path):
    data = load_project(short_demo)
    data["shots"][1]["layers"] = data["shots"][1]["layers"][:1]
    write_json(short_demo / "project.json", data)
    before = render_project(short_demo)
    second = short_demo / before[1]["output"]
    old_mtime = second.stat().st_mtime_ns
    replacement = tmp_path / "new-foreground.png"
    Image.new("RGBA", (1280, 720), (100, 50, 20, 80)).save(replacement)
    register_asset(short_demo, replacement, "FG", "test replacement")
    after = render_project(short_demo)
    assert not after[0]["cached"] and after[1]["cached"]
    assert after[0]["output"] != before[0]["output"]
    assert second.stat().st_mtime_ns == old_mtime
