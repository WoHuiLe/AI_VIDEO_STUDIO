import copy
import csv
import io
import zipfile

import pytest
from PIL import Image, ImageChops

from avstudio.delivery import package
from avstudio.demo import create_demo
from avstudio.media import export_srt, import_timeline
from avstudio.project import (attach_audio, import_storyboard, init_project,
                              register_asset, require_valid, validate)
from avstudio.render import frame, render_project, signature
from avstudio.storage import StudioError, load_project, local, read_json, sha256, write_json


@pytest.fixture
def demo(tmp_path):
    root = tmp_path / "测试项目 with space"
    create_demo(root)
    return root


def test_init_preserves_original_and_no_invented_timings(tmp_path):
    script = tmp_path / "原文.txt"
    script.write_text("第一段。\n\n第二段。", encoding="utf-8")
    root = tmp_path / "project"
    data = init_project(root, script, "test")
    assert sha256(root / data["script"]) == sha256(script)
    assert len(data["segments"]) == 2
    assert data["shots"] == [] and data["narration"] is None
    with pytest.raises(StudioError, match="非空"):
        init_project(root, script, "overwrite")


@pytest.mark.parametrize("path", ["../outside", "C:/outside", "assets/../../secret", ""])
def test_paths_cannot_escape_project(tmp_path, path):
    with pytest.raises(StudioError):
        local(tmp_path, path)


def test_replacing_asset_keeps_original_and_only_invalidates_dependents(demo, tmp_path):
    data = require_valid(demo)
    # Second shot no longer uses foreground, so it should keep its cache key.
    data["shots"][1]["layers"] = data["shots"][1]["layers"][:1]
    write_json(demo / "project.json", data)
    before = [signature(data, s) for s in data["shots"]]
    old = local(demo, data["assets"]["FG"]["path"])
    image = tmp_path / "replacement.png"
    Image.new("RGBA", (1280, 720), (12, 35, 50, 100)).save(image)
    register_asset(demo, image, "FG", "test replacement")
    after = require_valid(demo)
    keys = [signature(after, s) for s in after["shots"]]
    assert before[0] != keys[0] and before[1] == keys[1]
    assert old.exists()


def test_corrupted_asset_and_original_are_detected(demo):
    data = load_project(demo)
    local(demo, data["assets"]["BG"]["path"]).write_bytes(b"changed")
    local(demo, data["script"]).write_text("changed", encoding="utf-8")
    issues = validate(data, demo)
    assert any("素材内容改变" in x for x in issues)
    assert any("原始文案已变化" in x for x in issues)


def test_invalid_references_motion_and_timeline(demo):
    data = load_project(demo)
    data["shots"][0]["layers"][0]["end"] = [1, 0, 1]
    data["shots"][1]["segment_ids"] = ["missing"]
    data["shots"][1]["timeline_status"] = "aligned"
    errors = validate(data, demo)
    assert any("画布边缘" in x for x in errors)
    assert any("不存在的文案" in x for x in errors)
    assert any("对齐必须" in x for x in errors)


def test_storyboard_csv_roundtrip_retains_layers(demo):
    path = demo / "planning/storyboard.csv"
    original = load_project(demo)
    assert import_storyboard(demo, path) == 2
    data = require_valid(demo)
    assert data["shots"][0]["layers"] == original["shots"][0]["layers"]
    assert data["shots"][0]["start_s"] is None


def test_failed_csv_import_is_atomic(demo):
    path = demo / "planning/storyboard.csv"
    before = (demo / "project.json").read_bytes()
    path.write_text(path.read_text(encoding="utf-8-sig").replace("SEG001", "UNKNOWN"), encoding="utf-8")
    with pytest.raises(StudioError):
        import_storyboard(demo, path)
    assert (demo / "project.json").read_bytes() == before


def test_full_render_requires_review(demo):
    data = load_project(demo)
    data["shots"][0]["review_status"] = "draft"
    write_json(demo / "project.json", data)
    with pytest.raises(StudioError, match="approved"):
        render_project(demo)


def test_subpixel_transform_is_continuous():
    image = Image.new("RGBA", (200, 100), "white")
    for y in range(100):
        image.putpixel((100, y), (0, 0, 0, 255))
    spec = [{"start": [-0.01, 0, 1.1], "end": [0.01, 0, 1.1]}]
    first = frame([image], spec, image.size, 0.49)
    second = frame([image], spec, image.size, 0.5)
    assert ImageChops.difference(first, second).getbbox() is not None
    assert first.getpixel((0, 50)) == (255, 255, 255)


def test_package_is_portable_and_manifest_matches(demo):
    path = package(demo)
    with zipfile.ZipFile(path) as archive:
        import hashlib
        import json
        manifest = json.loads(archive.read("PACKAGE_MANIFEST.json"))
        assert "HANDOFF.md" in archive.namelist()
        assert not any(n.startswith("/") or ".." in n.split("/") for n in archive.namelist())
        for entry in manifest:
            assert hashlib.sha256(archive.read(entry["path"])).hexdigest() == entry["sha256"]
        restored = demo.parent / "restored"
        archive.extractall(restored)
    assert require_valid(restored)["title"] == load_project(demo)["title"]


def test_cannot_export_unaligned_subtitles(demo):
    with pytest.raises(StudioError, match="校准"):
        export_srt(demo)


def test_malformed_manifest_is_reported_not_crashed(demo):
    data = load_project(demo)
    data["assets"] = []
    assert "assets" in validate(data, demo)[0]
    write_json(demo / "project.json", [])
    with pytest.raises(StudioError, match="版本"):
        load_project(demo)
