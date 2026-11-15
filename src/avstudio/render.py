"""CPU image/layer animation using subpixel affine transforms and rawvideo."""

import hashlib
import json
import math
import os
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageOps, __version__ as pillow_version

from .media import executable, inspect_media, probe, run
from .project import require_valid
from .storage import StudioError, event, local, read_json, sha256, write_json

RENDER_VERSION = "1"


def geometry(data: dict, preview: bool) -> tuple[int, int]:
    width, height = data["width"], data["height"]
    if preview and width > 640:
        height = max(2, round(height * 640 / width / 2) * 2)
        width = 640
    return width, height


def frame_count(duration: float, fps: int) -> int:
    # Always at least one frame. Expose actual duration in receipts.
    return max(1, math.floor(duration * fps + 0.5))


def signature(data: dict, shot: dict, preview=False) -> str:
    payload = {"engine": RENDER_VERSION, "pillow": pillow_version,
               "size": geometry(data, preview), "fps": data["fps"],
               "frames": frame_count(shot["duration_s"], data["fps"]),
               "layers": shot["layers"],
               "assets": {l["asset_id"]: data["assets"][l["asset_id"]]["sha256"]
                          for l in shot["layers"]}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def frame(layers: list, spec: list, size: tuple, progress: float) -> Image.Image:
    """Shared canvas, front-to-back compositing, smooth continuous sampling."""
    width, height = size
    ease = progress * progress * (3 - 2 * progress)
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    for image, layer in zip(layers, spec):
        x, y, scale = [a + (b - a) * ease for a, b in zip(layer["start"], layer["end"])]
        inverse = (1 / scale, 0, width / 2 - width / (2 * scale) - x * width / scale,
                   0, 1 / scale, height / 2 - height / (2 * scale) - y * height / scale)
        moved = image.transform(size, Image.Transform.AFFINE, inverse,
                                resample=Image.Resampling.BICUBIC)
        canvas = Image.alpha_composite(canvas, moved)
    return canvas.convert("RGB")


def render_shot(root: Path, data: dict, shot: dict, preview=False) -> dict:
    key = signature(data, shot, preview)
    folder = local(root, "work/previews" if preview else "work/shots")
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / f"{shot['shot_id']}_{key[:16]}.mp4"
    receipt_path = output.with_suffix(".json")
    if output.exists() and receipt_path.exists():
        receipt = read_json(receipt_path)
        if receipt.get("signature") == key and receipt.get("output_sha256") == sha256(output):
            return {**receipt, "cached": True}
    size = geometry(data, preview)
    layers = []
    for spec in shot["layers"]:
        asset = data["assets"][spec["asset_id"]]
        with Image.open(local(root, asset["path"])) as original:
            layers.append(ImageOps.fit(ImageOps.exif_transpose(original).convert("RGBA"),
                                       size, method=Image.Resampling.LANCZOS))
    if layers[0].getchannel("A").getextrema()[0] != 255:
        raise StudioError(f"{shot['shot_id']} 底层背景必须不透明并已补齐")
    frames = frame_count(shot["duration_s"], data["fps"])
    fd, temp_name = tempfile.mkstemp(dir=folder, suffix=".mp4")
    os.close(fd)
    temp = Path(temp_name)
    try:
        # Stderr goes to a temporary file to avoid pipe backpressure deadlocks.
        with tempfile.TemporaryFile() as error_log:
            proc = subprocess.Popen(
                [executable("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                 "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{size[0]}x{size[1]}",
                 "-r", str(data["fps"]), "-i", "pipe:0", "-an", "-c:v", "libx264",
                 "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
                 "-movflags", "+faststart", str(temp)],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=error_log)
            try:
                for index in range(frames):
                    image = frame(layers, shot["layers"], size, index / max(1, frames - 1))
                    proc.stdin.write(image.tobytes())
                proc.stdin.close()
                code = proc.wait(timeout=300)
                if code:
                    error_log.seek(0)
                    raise StudioError(error_log.read().decode("utf-8", errors="replace")[-4000:])
            except BaseException:
                if proc.poll() is None:
                    proc.kill()
                proc.wait()
                if not proc.stdin.closed:
                    proc.stdin.close()
                raise
        inspection = inspect_media(temp)
        os.replace(temp, output)
        inspection["file"] = output.relative_to(root).as_posix()
        receipt = {"signature": key, "output": output.relative_to(root).as_posix(),
                   "output_sha256": sha256(output), "frames": frames,
                   "actual_duration_s": frames / data["fps"], "shot_id": shot["shot_id"],
                   "preview": preview, "inspection": inspection, "cached": False}
        write_json(receipt_path, receipt)
        event(root, "render", {"shot_id": shot["shot_id"], "output": receipt["output"]})
        return receipt
    finally:
        temp.unlink(missing_ok=True)


def render_project(root: Path, preview=False, shot_id=None) -> list:
    data = require_valid(root)
    selected = [s for s in data["shots"] if shot_id is None or s["shot_id"] == shot_id]
    if not selected:
        raise StudioError("没有匹配的镜头")
    if not preview and any(s["review_status"] != "approved" for s in selected):
        raise StudioError("正式镜头需先将 review_status 设为 approved；草稿用 --preview")
    return [render_shot(root, data, s, preview) for s in selected]


def current_render(root: Path, data: dict, shot: dict, preview=False) -> Path:
    key = signature(data, shot, preview)
    folder = "work/previews" if preview else "work/shots"
    path = local(root, f"{folder}/{shot['shot_id']}_{key[:16]}.mp4")
    if not path.exists() or not path.with_suffix(".json").exists():
        raise StudioError(f"{shot['shot_id']} 当前素材/参数没有对应渲染，请先 render")
    receipt = read_json(path.with_suffix(".json"))
    if receipt.get("signature") != key or receipt.get("output_sha256") != sha256(path):
        raise StudioError(f"{shot['shot_id']} 渲染文件已改变，请重新 render")
    return path


def assemble(root: Path, preview=False) -> dict:
    data = require_valid(root)
    if not data["shots"]:
        raise StudioError("没有镜头")
    if not preview and any(s["review_status"] != "approved" for s in data["shots"]):
        raise StudioError("存在尚未审核的镜头")
    aligned = [s["timeline_status"] == "aligned" for s in data["shots"]]
    if any(aligned) and not all(aligned):
        raise StudioError("不能混合已对齐和临时时间，请先统一时间轴")
    paths = [current_render(root, data, shot, preview) for shot in data["shots"]]
    cursor = 0.0
    timeline = []
    for shot in data["shots"]:
        duration = frame_count(shot["duration_s"], data["fps"]) / data["fps"]
        if all(aligned) and abs(shot["start_s"] - cursor) > 1 / data["fps"]:
            raise StudioError("首版顺序合成不支持时间轴空隙或重叠；请调整镜头或在剪映处理")
        timeline.append({"shot_id": shot["shot_id"], "start_s": cursor,
                         "end_s": cursor + duration, "timeline_status": shot["timeline_status"]})
        cursor += duration
    audio = local(root, data["narration"]) if data.get("narration") else None
    if audio and not all(aligned):
        raise StudioError("含旁白粗剪须先导入已确认的真实时间轴；临时镜头可独立交付")
    if audio and float(probe(audio)["format"]["duration"]) > cursor + 1 / data["fps"]:
        raise StudioError("镜头短于旁白，拒绝截断声音；请增加镜头时长")
    output_folder = root / "output"
    output_folder.mkdir(exist_ok=True)
    fd, list_name = tempfile.mkstemp(dir=root / "work", suffix=".txt")
    os.close(fd)
    concat = Path(list_name)
    # Escape paths for concat demuxer, not for a shell (no shell=True anywhere).
    concat.write_text("\n".join("file '" + p.resolve().as_posix().replace("'", "'\\''") + "'"
                                for p in paths), encoding="utf-8")
    key = hashlib.sha256(json.dumps({"renders": [sha256(p) for p in paths],
                                    "audio": data.get("narration_sha256")}, sort_keys=True).encode()).hexdigest()[:16]
    output = output_folder / f"{'preview' if preview else 'roughcut'}_{key}.mp4"
    fd, temp_name = tempfile.mkstemp(dir=output_folder, suffix=".mp4")
    os.close(fd)
    temp = Path(temp_name)
    try:
        args = [executable("ffmpeg"), "-hide_banner", "-v", "error", "-y",
                "-f", "concat", "-safe", "0", "-i", str(concat.resolve())]
        if audio:
            args += ["-i", str(audio), "-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac",
                     "-ar", "48000", "-ac", "2", "-af", "apad", "-t", str(cursor)]
        else:
            args += ["-map", "0:v:0", "-an"]
        args += ["-c:v", "copy", "-sn", "-movflags", "+faststart", str(temp)]
        run(args, timeout=3600)
        report = inspect_media(temp)
        os.replace(temp, output)
        report["file"] = output.relative_to(root).as_posix()
        result = {"output": report["file"], "timeline": timeline, "inspection": report,
                  "output_sha256": sha256(output),
                  "note": "首版为顺序直切，无字幕；设计的转场和配乐可在剪映精修"}
        write_json(output.with_suffix(".json"), result)
        event(root, "assemble", {"output": result["output"]})
        return result
    finally:
        concat.unlink(missing_ok=True)
        temp.unlink(missing_ok=True)
