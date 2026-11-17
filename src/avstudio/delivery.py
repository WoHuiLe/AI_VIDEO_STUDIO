"""Explicit portable handoff packages; no private app draft database writes."""

import csv
import io
import json
import os
import tempfile
import zipfile
from pathlib import Path

from .project import export_assets, export_storyboard, require_valid
from .render import current_render
from .storage import StudioError, atomic_text, event, local, read_json, sha256


def package(root: Path, include_renders=False, assembled=None) -> Path:
    data = require_valid(root)
    export_storyboard(root)
    export_assets(root)
    files = {local(root, "project.json"), local(root, data["script"]),
             local(root, "planning/storyboard.csv"), local(root, "planning/assets.csv")}
    if assembled:
        video = local(root, assembled)
        receipt = read_json(video.with_suffix(".json"))
        if receipt.get("output_sha256") != sha256(video):
            raise StudioError("合成视频校验失败")
        files.update([video, video.with_suffix(".json")])
    for name in ["visual_task.md", "handoff.md", "character_bible.md", "style.md",
                 "review_notes.md", "prompts.md", "director.json", "shot_assets.json",
                 "brief.md", "submission.json", "feedback.json"]:
        path = local(root, f"planning/{name}")
        if path.exists():
            files.add(path)
    for path in (root / "planning").glob("storyboard_*.md"):
        files.add(local(root, path.relative_to(root).as_posix()))
    overrides = {}
    submission_file = local(root, "planning/submission.json")
    if submission_file.exists():
        snapshot = read_json(submission_file)
        snapshot["active_job"] = None
        if snapshot.get("status") == "working":
            snapshot["status"] = "review"
        overrides["planning/submission.json"] = (json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        for record in snapshot.get("files", []):
            source = local(root, record["path"])
            if not source.is_file():
                raise StudioError("交接资料缺失：" + record.get("name", record["path"]))
            files.add(source)
    for asset in data["assets"].values():
        files.add(local(root, asset["path"]))
    if data.get("narration"):
        files.add(local(root, data["narration"]))
    if include_renders:
        for shot in data["shots"]:
            if shot["review_status"] != "approved":
                raise StudioError("镜头包存在未审核镜头")
            video = current_render(root, data, shot)
            files.update([video, video.with_suffix(".json")])
    manifest = []
    for path in sorted(files):
        relative = path.relative_to(root.resolve()).as_posix()
        payload = overrides.get(relative)
        manifest.append({"path": relative,
                         "sha256": __import__("hashlib").sha256(payload).hexdigest() if payload is not None else sha256(path),
                         "bytes": len(payload) if payload is not None else path.stat().st_size})
    # Hash every included byte, including handoff notes, not just video parameters.
    digest = __import__("hashlib").sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()[:16]
    output = local(root, f"output/handoff_{digest}.zip")
    output.parent.mkdir(parents=True, exist_ok=True)
    notes = (f"# {data['title']}：剪映/跨 AI 交接\n\n"
             f"范围：{'独立镜头和源素材' if include_renders else '策划与图片素材'}。\n\n"
             "从 planning/handoff.md 和 project.json 读取状态，勿将 draft 当作已审核。\n"
             "在剪映中按 planning/storyboard.csv 排序导入独立镜头或图片；旁白按需导入。\n"
             "镜头内图层已烘焙；修改图层需用源素材重新渲染。\n"
             "没有实际录音校准时，时长只是剪辑参考。\n"
             "视觉一致性、叙事和听音验收以用户/审核者记录为准，技术通过不能替代。\n"
             "本包不修改剪映草稿，不包含软件、模型、密钥或系统配置。\n")
    fd, temp_name = tempfile.mkstemp(dir=output.parent, prefix=".writing-", suffix=".zip")
    os.close(fd)
    temp = Path(temp_name)
    try:
        with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, entry in zip(sorted(files), manifest):
                if entry["path"] in overrides:
                    archive.writestr(entry["path"], overrides[entry["path"]])
                else:
                    archive.write(path, entry["path"])
            archive.writestr("PACKAGE_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            archive.writestr("HANDOFF.md", notes)
        with zipfile.ZipFile(temp) as archive:
            bad = archive.testzip()
            if bad:
                raise StudioError(f"交接包校验失败：{bad}")
        os.replace(temp, output)
        event(root, "package", {"output": output.relative_to(root).as_posix()})
        return output
    finally:
        temp.unlink(missing_ok=True)
