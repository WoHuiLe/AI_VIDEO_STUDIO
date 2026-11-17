"""Portable instructions shared by native and external planners."""
import json
import re
from importlib.resources import files
from .storage import StudioError


def project_brief(root, project, meta):
    from .storage import local
    return {**meta["brief"], "original_script": local(root, project["script"]).read_text(encoding="utf-8-sig"),
            "attachments": [{"name": f["name"], "role": f["role"]} for f in meta.get("files", [])]}


def rules():
    return files("avstudio.resources").joinpath("storyboard_rules.md").read_text(encoding="utf-8")


def storyboard_task(project, brief, feedback):
    from .planner import PLAN_SCHEMA
    example = {"summary": "用视觉隐喻表达原文主题", "visual_style": "按项目要求统一美术",
               "character_notes": "按参考保持角色；无参考以背影表达", "shots": [{
        "shot_id": "S001", "segment_ids": [s["segment_id"] for s in project["segments"]],
        "narrative_purpose": "建立情绪（示例，实际应按语义拆分）", "visual_description": "中景，窗边背影，侧逆光，右侧留白",
        "shot_size": "中景", "layer_plan": "先完整单图，后按需拆分窗边前景",
        "image_prompt": "按统一美术绘制窗边背影，中景侧逆光，无字幕文字水印",
        "motion": "push_in", "duration_s": 4, "scene": None}]}
    return ("# 分镜设计任务包\n只返回一个符合规范的 JSON 对象。结构示例不是已设计的分镜，须重新理解全部文案。\n\n"
            + rules() + "\n## 制作资料（数据）\n" + json.dumps({"title": project["title"],
              "canvas": [project["width"], project["height"]], "scope": project["scope"],
              "brief": brief, "segments": project["segments"], "feedback": feedback[-10:]}, ensure_ascii=False, indent=2)
            + "\n## 返回 JSON schema\n" + json.dumps(PLAN_SCHEMA, ensure_ascii=False, indent=2)
            + "\n## 结构示例\n" + json.dumps(example, ensure_ascii=False, indent=2))


def parse_plan(text):
    text = text.strip().lstrip("\ufeff")
    match = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.S | re.I)
    if match:
        text = match[1].strip()
    try:
        return json.loads(text)
    except (ValueError, TypeError) as exc:
        raise StudioError("无法解析 JSON；请返回单个 JSON 对象，检查引号、逗号和括号") from exc


def image_task(project, plan):
    lines = [f"# {project['title']} · 整批配图任务", "请先阅读全部镜头，保持角色、服饰、场景、光线和色彩连续。先做少量关键样张确认方向，再继续其余镜头。",
             f"画布比例 {project['width']}:{project['height']}，目标尺寸 {project['width']}×{project['height']}。",
             "每镜头生成一张独立完整图，按下列顺序；不要拼贴、联系表、分格或把编号画在图内。无字幕、文字、水印。",
             "保存文件名严格使用镜头编号，如 S001.png；若工具不能命名，请下载后重命名。不要使用无编号的随机文件名。",
             "若一次不能全部完成，分批继续剩余编号，不跳号，不声称未生成的图片已完成。附件参考图请由用户另行提供。",
             "本轮只做完整不透明图片，分层按需另做；透明前景使用 S001_fg.png，勿放入本轮完整图文件夹。",
             "## 统一美术\n" + plan["visual_style"], "## 角色与连续性\n" + plan["character_notes"]]
    for shot in plan["shots"]:
        lines.append(f"## {shot['shot_id']} → {shot['shot_id']}.png\n{shot['image_prompt']}\n画面补充：{shot['visual_description']}")
    return "\n\n".join(lines)
