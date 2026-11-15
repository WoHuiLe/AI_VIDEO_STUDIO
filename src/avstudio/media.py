"""FFmpeg execution, deterministic media inspection and audio import helpers."""

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import __version__ as pillow_version

from .storage import StudioError, atomic_text, load_project, local, write_json


def executable(name: str) -> str:
    path = os.environ.get(f"AVSTUDIO_{name.upper()}") or shutil.which(name)
    if not path or not Path(path).is_file():
        raise StudioError(f"找不到 {name}；可用 AVSTUDIO_{name.upper()} 指定现有程序")
    return str(path)


def run(args: list[str], timeout=300) -> str:
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=timeout, check=False, encoding="utf-8", errors="replace")
    if result.returncode:
        raise StudioError(f"{Path(args[0]).name} 执行失败：{result.stderr[-4000:]}")
    return result.stdout


def probe(path: Path) -> dict:
    return json.loads(run([executable("ffprobe"), "-v", "error", "-show_format",
                           "-show_streams", "-of", "json", str(path.resolve())]))


def inspect_media(path: Path, decode=True) -> dict:
    info = probe(path)
    checks = {"probe": "PASS", "full_decode": "NOT_RUN",
              "no_subtitle_stream": "PASS" if not any(
                  s["codec_type"] == "subtitle" for s in info["streams"]) else "FAIL",
              "visual_review": "NOT_RUN", "listening_review": "NOT_RUN"}
    if decode:
        # -xerror makes corrupt packets/decoder errors fail rather than just log.
        run([executable("ffmpeg"), "-hide_banner", "-v", "error", "-xerror",
             "-i", str(path.resolve()), "-f", "null", "-"], timeout=3600)
        checks["full_decode"] = "PASS"
    return {"file": str(path), "checks": checks, "media": info,
            "note": "技术检查不代表叙事、美术、无烧录文字或听音验收通过"}


def doctor() -> dict:
    tools = {}
    for name in ["ffmpeg", "ffprobe", "git"]:
        try:
            path = executable(name)
            flag = "--version" if name == "git" else "-version"
            tools[name] = {"path": path, "version": run([path, flag]).splitlines()[0],
                           "status": "PASS"}
        except (StudioError, OSError, subprocess.TimeoutExpired) as exc:
            tools[name] = {"status": "FAIL", "error": str(exc)}
    disk = shutil.disk_usage(Path.cwd())
    return {"python": sys.version, "python_executable": sys.executable,
            "platform": platform.platform(), "pillow": pillow_version,
            "free_bytes": disk.free, "tools": tools,
            "voice_api": "NOT_RUN", "capcut_import": "NOT_RUN"}


def import_timeline(root: Path, path: Path, confirmed=False) -> int:
    """Accept reviewed audio timings, never infer them from character counts."""
    from .project import validate
    from .storage import event, read_json

    data = load_project(root)
    if not data.get("narration"):
        raise StudioError("先用 audio 导入实际旁白")
    if not confirmed:
        raise StudioError("校准需用 --confirmed 声明已对照真实旁白复核")
    duration = float(probe(local(root, data["narration"]))["format"]["duration"])
    timings = read_json(path)
    if not isinstance(timings, list) or len({t["shot_id"] for t in timings}) != len(timings):
        raise StudioError("时间轴须为不重复的镜头对象列表")
    known = {s["shot_id"]: s for s in data["shots"]}
    for item in timings:
        if item["shot_id"] not in known:
            raise StudioError("时间轴包含未知镜头")
        start, end = float(item["start_s"]), float(item["end_s"])
        if end > duration + 1 / data["fps"]:
            raise StudioError("时间轴超出真实旁白")
        shot = known[item["shot_id"]]
        shot.update(start_s=start, end_s=end, duration_s=end - start,
                    timeline_status="aligned", sync_anchor=item.get("sync_anchor", ""),
                    alignment_audio_sha256=data["narration_sha256"])
    errors = validate(data, root)
    if errors:
        raise StudioError("\n".join(errors))
    write_json(root / "project.json", data)
    event(root, "import_timeline", {"count": len(timings), "confirmed": True})
    return len(timings)


def export_srt(root: Path) -> Path:
    from .project import require_valid

    data = require_valid(root)
    if not data["shots"] or any(s.get("timeline_status") != "aligned" for s in data["shots"]):
        raise StudioError("导出字幕前，所有镜头须以真实旁白校准")
    # Shot boundaries do not necessarily equal sentence boundaries. This is
    # explicitly a draft for review, never a claim of word-level ASR alignment.
    def stamp(seconds):
        ms = round(seconds * 1000)
        hour, ms = divmod(ms, 3600000)
        minute, ms = divmod(ms, 60000)
        second, ms = divmod(ms, 1000)
        return f"{hour:02}:{minute:02}:{second:02},{ms:03}"

    ordered = sorted(data["shots"], key=lambda s: s["start_s"])
    if any(a["end_s"] > b["start_s"] for a, b in zip(ordered, ordered[1:])):
        raise StudioError("镜头时间重叠，请先提供不重叠的字幕分段")
    blocks = [f"{i}\n{stamp(s['start_s'])} --> {stamp(s['end_s'])}\n{s['source_text']}\n"
              for i, s in enumerate(ordered, 1)]
    path = root / "output/subtitles_draft.srt"
    atomic_text(path, "\n".join(blocks))
    return path
