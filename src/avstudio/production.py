"""Validated storyboard → explicit approval → mapped art → rendered delivery."""

import copy
import hashlib
import json
import shutil
from pathlib import Path

from PIL import Image

from .delivery import package
from .planner import plan_with_codex, validate_plan
from .project import export_storyboard, image_info, register_asset, require_valid
from .render import assemble, current_render, render_shot
from .storage import StudioError, atomic_text, load_project, local, read_json, sha256, write_json


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class Production:
    def __init__(self, desk, planner=None):
        self.desk = desk
        self.planner = planner or plan_with_codex

    def meta(self, root):
        return read_json(local(root, "planning/submission.json"))

    def update(self, root, **changes):
        meta = self.meta(root)
        meta.update(updated_at=self.desk.now(), **changes)
        write_json(root / "planning/submission.json", meta)

    def idle(self, root):
        if self.meta(root).get("active_job"):
            raise StudioError("任务正在执行，请等待完成或先取消，再修改资料")

    def plan(self, root):
        path = local(root, "planning/director.json")
        if not path.is_file():
            raise StudioError("请先开始设计分镜，或导入分镜 JSON")
        return validate_plan(read_json(path), require_valid(root))

    def approved(self, root, stage):
        approvals = self.meta(root).get("approvals", {})
        if stage == "storyboard":
            return approvals.get(stage) == digest(self.plan(root))
        return approvals.get(stage) == self.art_revision(root)

    def art_revision(self, root):
        data = require_valid(root)
        mapping = self.mapping(root)
        return digest({"plan": digest(self.plan(root)), "mapping": mapping,
                       "assets": {key: asset["sha256"] for key, asset in data["assets"].items()
                                  if any(key == m.get("background") or key in m.get("foregrounds", [])
                                         for m in mapping.values())}})

    def mapping(self, root):
        path = local(root, "planning/shot_assets.json")
        return read_json(path) if path.exists() else {}

    def adopt(self, root, plan):
        data = require_valid(root)
        validate_plan(plan, data)
        revision = digest(plan)
        write_json(root / f"planning/director_{revision[:12]}.json", plan)
        write_json(root / "planning/director.json", plan)
        write_json(root / "planning/shot_assets.json", {})
        data["shots"] = []
        write_json(root / "project.json", data)
        lines = [f"# {data['title']} · 导演分镜\n", "状态：待审核；所有时长均为临时剪辑参考，尚未按旁白校准。\n",
                 "## 内容理解\n" + plan["summary"], "## 美术方向\n" + plan["visual_style"],
                 "## 角色与连续性\n" + plan["character_notes"]]
        for shot in plan["shots"]:
            lines.append(f"## {shot['shot_id']}\n对应段落：{', '.join(shot['segment_ids'])}\n\n"
                         f"叙事目的：{shot['narrative_purpose']}\n\n画面：{shot['visual_description']}\n\n"
                         f"景别：{shot['shot_size']}；运镜：{shot['motion']}\n\n分层：{shot['layer_plan']}\n")
        atomic_text(root / f"planning/storyboard_{revision[:12]}.md", "\n\n".join(lines))
        from .taskpacks import image_task
        atomic_text(root / "planning/prompts.md", image_task(data, plan))
        atomic_text(root / "planning/style.md", "# 美术设定\n\n" + plan["visual_style"] + "\n\n" + plan["character_notes"])
        export_storyboard(root)
        self.update(root, status="review", current_stage="storyboard", review_stage="storyboard",
                    approvals={}, error=None, plan_revision=revision, needs_revision=False)

    def approve(self, root, stage):
        self.idle(root)
        meta = self.meta(root)
        approvals = meta.get("approvals", {})
        if stage == "storyboard":
            if meta.get("needs_revision"):
                raise StudioError("已提出分镜修改，请先重新设计或导入新版分镜后再确认")
            approvals[stage] = digest(self.plan(root))
            self.update(root, approvals=approvals, status="awaiting_assets", current_stage="artwork",
                        review_stage="artwork", error=None)
        elif stage == "artwork":
            self.ensure_art(root)
            approvals[stage] = self.art_revision(root)
            data = require_valid(root)
            for shot in data["shots"]:
                shot["review_status"] = "approved"
            write_json(root / "project.json", data)
            self.update(root, approvals=approvals, status="review", current_stage="delivery", error=None)
        else:
            raise StudioError("当前没有这个部分可以审核")

    def ensure_art(self, root):
        if not self.approved(root, "storyboard"):
            raise StudioError("请先审核分镜方案")
        plan = self.plan(root)
        mapping = self.mapping(root)
        missing = [s["shot_id"] for s in plan["shots"] if not s.get("scene") and not mapping.get(s["shot_id"], {}).get("background")]
        if missing:
            raise StudioError("这些镜头还缺图片或干净背景：" + "、".join(missing))
        if load_project(root)["scope"] == "layers" and not any(m.get("foregrounds") for m in mapping.values()):
            raise StudioError("分层素材至少需要一组背景和透明前景，不能将完整单图冒充为分层交付")
        require_valid(root)

    def bind(self, root, shot_id, role, source):
        self.idle(root)
        if not self.approved(root, "storyboard"):
            raise StudioError("请先审核分镜，再上传镜头配图")
        if shot_id not in {s["shot_id"] for s in self.plan(root)["shots"]} or role not in {"background", "foreground"}:
            raise StudioError("镜头编号或图层类型无效")
        info = image_info(source)
        with Image.open(source) as image:
            extrema = image.convert("RGBA").getchannel("A").getextrema()
        if role == "background" and extrema[0] != 255:
            raise StudioError("背景/完整图必须不透明；透明 PNG 请作为前景上传")
        if role == "foreground" and extrema[0] == 255:
            raise StudioError("前景需要真实透明区域，请使用透明 PNG")
        mapping = self.mapping(root)
        entry = mapping.setdefault(shot_id, {"foregrounds": []})
        data = require_valid(root)
        companions = ([entry["background"]] if entry.get("background") and role == "foreground" else []) + entry.get("foregrounds", [])
        for aid in companions:
            asset = data["assets"][aid]
            if (info["width"], info["height"]) != (asset["width"], asset["height"]):
                raise StudioError("同一镜头的背景和透明前景必须使用相同画布尺寸")
        asset = register_asset(root, source, f"ART_{shot_id}_{sha256(source)[:10]}", "网页镜头素材")
        if role == "background":
            entry["background"] = asset["asset_id"]
        elif asset["asset_id"] not in entry["foregrounds"]:
            entry["foregrounds"].append(asset["asset_id"])
        write_json(root / "planning/shot_assets.json", mapping)
        self.rebuild(root)
        meta = self.meta(root)
        approvals = meta.get("approvals", {})
        approvals.pop("artwork", None)
        self.update(root, status="awaiting_assets", current_stage="artwork", approvals=approvals, error=None)

    def unbind(self, root, shot_id, asset_id):
        self.idle(root)
        mapping = self.mapping(root)
        entry = mapping.get(shot_id)
        if not entry or asset_id not in entry.get("foregrounds", []):
            raise StudioError("找不到这个前景图层")
        entry["foregrounds"].remove(asset_id)
        write_json(root / "planning/shot_assets.json", mapping)
        self.rebuild(root)
        approvals = self.meta(root).get("approvals", {})
        approvals.pop("artwork", None)
        self.update(root, status="awaiting_assets", current_stage="artwork", approvals=approvals)

    def rebuild(self, root):
        data = require_valid(root)
        old = {s["shot_id"]: s for s in data["shots"]}
        mapping = self.mapping(root)
        segments = {s["segment_id"]: s["text"] for s in data["segments"]}
        shots = []
        for planned in self.plan(root)["shots"]:
            mapped = mapping.get(planned["shot_id"], {})
            if not mapped.get("background") and not planned.get("scene"):
                continue
            motion = planned["motion"]
            start, end = [0, 0, 1.06], [0, 0, 1.06]
            if motion == "push_in": end = [0, 0, 1.12]
            if motion == "pull_out": start = [0, 0, 1.12]
            if motion == "pan_left": start, end = [0.02, 0, 1.08], [-0.02, 0, 1.08]
            if motion == "pan_right": start, end = [-0.02, 0, 1.08], [0.02, 0, 1.08]
            shot = {**planned, "source_text": "\n".join(segments[s] for s in planned["segment_ids"]),
                    "start_s": None, "end_s": None, "timeline_status": "provisional",
                    "review_status": "needs_review", "layers": [] if planned.get("scene") else [
                        {"asset_id": mapped["background"], "start": start, "end": end}]}
            for aid in mapped.get("foregrounds", []):
                shot["layers"].append({"asset_id": aid, "start": [0.02, 0, 1.12], "end": [-0.02, 0, 1.12]})
            previous = old.get(shot["shot_id"], {})
            if previous.get("timeline_status") == "aligned":
                for key in ["start_s", "end_s", "timeline_status", "duration_s", "alignment_audio_sha256"]:
                    shot[key] = previous[key]
            shots.append(shot)
        data["shots"] = shots
        write_json(root / "project.json", data)
        require_valid(root)
        export_storyboard(root)

    def check_action(self, root, action):
        if action == "plan":
            require_valid(root)
        elif action in {"preview", "deliver"}:
            self.ensure_art(root)
            if action == "deliver" and not self.approved(root, "artwork"):
                raise StudioError("请先确认画面与图层，再生成交付")
            data = require_valid(root)
            if action == "deliver" and data["scope"] == "roughcut" and data.get("narration"):
                if any(s.get("timeline_status") != "aligned" for s in data["shots"]):
                    raise StudioError("旁白尚未校准，请先填写并确认镜头时间轴")
        else:
            raise StudioError("不支持这个制作任务")

    def execute(self, project_id, action, cancelled, progress):
        root = self.desk.project(project_id)
        if action == "plan":
            with self.desk.lock:
                data = copy.deepcopy(require_valid(root))
                meta = self.meta(root)
                feedback = read_json(root / "planning/feedback.json")
                from .taskpacks import project_brief
                brief = project_brief(root, data, meta)
            work = root / "work/planner" / meta["active_job"]
            progress({"message": "正在设计分镜，等待本机 Codex 返回；此阶段无法计算准确百分比", "stage": "planning"})
            plan = self.planner(data, brief, feedback, work, cancelled, progress)
            if cancelled.is_set(): raise StudioError("任务已取消")
            progress({"message": "分镜已返回，正在校验格式、原文覆盖与保存方案", "stage": "validating"})
            with self.desk.lock:
                self.adopt(root, plan)
            return
        data = require_valid(root)
        preview = action == "preview"
        if preview or data["scope"] in {"shots", "roughcut"}:
            for index, shot in enumerate(data["shots"], 1):
                if cancelled.is_set(): raise StudioError("任务已取消")
                progress({"message": f"正在渲染 {shot['shot_id']}（{index}/{len(data['shots'])}）；未变化镜头会复用缓存",
                          "stage": "rendering", "completed": index-1, "total": len(data["shots"]), "unit": "镜头"})
                receipt = render_shot(root, data, shot, preview, cancelled=cancelled)
                source = local(root, receipt["output"])
                target = root / "output" / source.name
                if not target.exists(): shutil.copyfile(source, target)
                progress({"message": f"已完成 {index}/{len(data['shots'])} 个镜头" + ("（复用缓存）" if receipt.get("cached") else ""),
                          "stage": "rendering", "completed": index, "total": len(data["shots"]), "unit": "镜头"})
        if cancelled.is_set(): raise StudioError("任务已取消")
        if preview:
            with self.desk.lock:
                self.update(root, status="review", current_stage="artwork", review_stage="artwork")
            return
        # Media work must not hold the global web lock or block progress reads.
        assembled = None
        if data["scope"] == "roughcut":
            progress({"message": "镜头渲染完成，正在合成整片并进行完整解码检查", "stage": "assembling"})
            assembled = assemble(root)["output"]
        progress({"message": "正在整理交付包、源素材与校验清单", "stage": "packaging"})
        output = package(root, include_renders=data["scope"] in {"shots", "roughcut"}, assembled=assembled)
        with self.desk.lock:
            self.update(root, status="complete", current_stage="delivery", delivery_file=output.relative_to(root).as_posix())

    def view(self, root):
        meta = self.meta(root)
        plan_path = local(root, "planning/director.json")
        plan = read_json(plan_path) if plan_path.exists() else None
        mapping = self.mapping(root)
        data = load_project(root)
        shots = []
        for shot in (plan or {}).get("shots", []):
            entry = mapping.get(shot["shot_id"], {})
            shots.append({**shot, "background": data["assets"].get(entry.get("background")),
                          "foregrounds": [data["assets"][aid] for aid in entry.get("foregrounds", [])],
                          "timing": next((s for s in data["shots"] if s["shot_id"] == shot["shot_id"]), None)})
        jobs = []
        for path in sorted((root / "work/jobs").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:8]:
            jobs.append(read_json(path))
        return {"stage": meta.get("current_stage", "storyboard"), "shots": shots, "jobs": jobs,
                "summary": (plan or {}).get("summary", ""),
                "visual_style": (plan or {}).get("visual_style", ""),
                "character_notes": (plan or {}).get("character_notes", ""),
                "approvals": meta.get("approvals", {}), "has_audio": bool(data.get("narration")),
                "audio_path": data.get("narration"), "error": meta.get("error"),
                "has_plan": plan is not None, "ready_count": sum(bool(s["background"] or s.get("scene")) for s in shots),
                "needs_revision": meta.get("needs_revision", False), "target_size": [data["width"], data["height"]]}
