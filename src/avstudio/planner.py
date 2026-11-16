"""A bounded, read-only Codex text planner; never executes model output as code."""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from .storage import StudioError, identifier, read_json, write_json

TEXT_FIELDS = ["narrative_purpose", "visual_description", "shot_size", "layer_plan", "image_prompt"]
SHOT_SCHEMA = {"type": "object", "additionalProperties": False, "properties": {
    "shot_id": {"type": "string"}, "segment_ids": {"type": "array", "items": {"type": "string"}},
    **{key: {"type": "string"} for key in TEXT_FIELDS},
    "motion": {"type": "string", "enum": ["static", "push_in", "pull_out", "pan_left", "pan_right"]},
    "duration_s": {"type": "number"}},
    "required": ["shot_id", "segment_ids", *TEXT_FIELDS, "motion", "duration_s"]}
PLAN_SCHEMA = {"type": "object", "additionalProperties": False, "properties": {
    "summary": {"type": "string"}, "visual_style": {"type": "string"},
    "character_notes": {"type": "string"},
    "shots": {"type": "array", "items": SHOT_SCHEMA}},
    "required": ["summary", "visual_style", "character_notes", "shots"]}


def codex_path():
    path = os.environ.get("AVSTUDIO_CODEX") or shutil.which("codex.exe") or shutil.which("codex")
    if not path or not Path(path).is_file():
        raise StudioError("找不到本机 Codex。请先安装并登录 Codex，或导入其他 AI 生成的分镜 JSON。")
    return str(Path(path).resolve())


def capability():
    try:
        path = codex_path()
        flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        result = subprocess.run([path, "login", "status"], capture_output=True, timeout=8, **flags)
        return {"available": result.returncode == 0,
                "message": "已连接本机 Codex" if result.returncode == 0 else "请先在本机 Codex 登录后再开始"}
    except (StudioError, OSError, subprocess.SubprocessError):
        return {"available": False, "message": "本机 Codex 尚不可用；也可导入其他 AI 的分镜和配图"}


def validate_plan(plan, project):
    if not isinstance(plan, dict):
        raise StudioError("分镜必须是 JSON 对象")
    for key in ["summary", "visual_style", "character_notes"]:
        if not isinstance(plan.get(key), str) or not 0 < len(plan[key]) <= 20000:
            raise StudioError(f"分镜缺少有效的 {key}")
    shots = plan.get("shots")
    if not isinstance(shots, list) or not 1 <= len(shots) <= 60:
        raise StudioError("分镜须包含 1–60 个镜头")
    known = {s["segment_id"] for s in project["segments"]}
    seen, covered = set(), set()
    import math
    for shot in shots:
        if not isinstance(shot, dict):
            raise StudioError("镜头格式无效")
        if not isinstance(shot.get("shot_id"), str):
            raise StudioError("镜头编号必须是字符串")
        sid = identifier(shot["shot_id"])
        if sid.casefold() in seen:
            raise StudioError("镜头编号重复")
        seen.add(sid.casefold())
        refs = shot.get("segment_ids")
        if not isinstance(refs, list) or not refs or any(not isinstance(s, str) or s not in known for s in refs):
            raise StudioError(f"{sid} 引用不存在的原文段落")
        covered.update(refs)
        for key in TEXT_FIELDS:
            if not isinstance(shot.get(key), str) or not 0 < len(shot[key]) <= 12000:
                raise StudioError(f"{sid} 缺少有效的 {key}")
        if shot.get("motion") not in SHOT_SCHEMA["properties"]["motion"]["enum"]:
            raise StudioError(f"{sid} 运镜类型无效")
        duration = shot.get("duration_s")
        if type(duration) not in {int, float} or not math.isfinite(duration) or not 0.1 <= duration <= 60:
            raise StudioError(f"{sid} 临时时长须为 0.1–60 秒")
    if known != covered:
        raise StudioError("分镜未覆盖全部原文段落")
    return plan


def plan_with_codex(project, brief, feedback, work: Path, cancelled, progress):
    path = codex_path()
    work.mkdir(parents=True, exist_ok=True)
    schema, output = work / "schema.json", work / "answer.json"
    write_json(schema, PLAN_SCHEMA)
    from .taskpacks import storyboard_task
    prompt = storyboard_task(project, brief, feedback)
    command = [path, "exec", "--sandbox", "read-only", "--ephemeral", "--skip-git-repo-check",
               "--output-schema", str(schema.resolve()), "--output-last-message", str(output.resolve()),
               "--json", "-"]
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    progress("正在调用本机 Codex 设计分镜，结果会经过结构和原文引用检查")
    with (work / "stderr.log").open("wb") as errors, (work / "events.jsonl").open("wb") as events:
        proc = subprocess.Popen(command, cwd=work, stdin=subprocess.PIPE, stdout=events, stderr=errors, **flags)
        started = time.monotonic()
        try:
            # No model-generated commands are accepted by this application.
            proc.stdin.write(prompt.encode("utf-8"))
            proc.stdin.close()
            while proc.poll() is None:
                if cancelled.is_set():
                    raise StudioError("任务已取消")
                if time.monotonic() - started > 600:
                    raise StudioError("分镜任务超过 10 分钟，请检查登录、网络或额度后重试")
                cancelled.wait(0.25)
            if proc.returncode != 0 or not output.is_file():
                raise StudioError("Codex 分镜执行失败，请检查登录、网络或额度；也可导入分镜文件")
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
    return validate_plan(read_json(output), project)
