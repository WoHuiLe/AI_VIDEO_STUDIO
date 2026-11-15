"""Synthetic geometry fixtures for rendering QA; not AI artwork or real projects."""

import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from .project import add_shot, export_storyboard, init_project, planning_packet, register_asset
from .storage import StudioError, atomic_text, load_project, write_json


def create_demo(root: Path) -> dict:
    if root.exists() and any(root.iterdir()):
        raise StudioError("演示目录非空，不覆盖")
    with tempfile.TemporaryDirectory() as temp:
        work = Path(temp)
        script = work / "script.txt"
        script.write_text("技术测试第一段：检查连续的图层视差。\n\n技术测试第二段：检查稳定运镜和镜头交接。", encoding="utf-8")
        data = init_project(root, script, "分层与运镜技术测试（非正式作品）", "shots")
        data.update(width=960, height=540, fps=24)
        write_json(root / "project.json", data)
        background = Image.new("RGB", (1280, 720), "#eee7da")
        draw = ImageDraw.Draw(background)
        for x in range(0, 1280, 80):
            draw.line((x, 0, x, 720), fill="#d8d2c8", width=1)
        for y in range(0, 720, 80):
            draw.line((0, y, 1280, y), fill="#d8d2c8", width=1)
        draw.ellipse((850, 100, 1050, 300), fill="#e4b975")
        draw.polygon([(0, 620), (280, 300), (700, 720), (0, 720)], fill="#a7b5ad")
        draw.polygon([(400, 720), (880, 380), (1280, 650), (1280, 720)], fill="#7f9b94")
        draw.text((100, 70), "SYNTHETIC QA / NOT AI ART", fill="#263c3c", font_size=30)
        background.save(work / "background.png")
        foreground = Image.new("RGBA", (1280, 720))
        front = ImageDraw.Draw(foreground)
        front.rectangle((30, 0, 80, 720), fill="#294a48")
        front.rectangle((1200, 0, 1250, 720), fill="#294a48")
        front.ellipse((160, 460, 350, 650), fill="#b66c52")
        foreground.save(work / "foreground.png")
        register_asset(root, work / "background.png", "BG", "程序生成测试素材", "project test fixture")
        register_asset(root, work / "foreground.png", "FG", "程序生成测试素材", "project test fixture")
    for i in range(1, 3):
        add_shot(root, f"S{i:03}", [f"SEG{i:03}"], "BG", 5,
                 "几何测试图：背景网格和透明前景相对运动", "检查渲染稳定性和交接，不评估创作效果")
    data = load_project(root)
    data["shots"][0]["layers"] = [
        {"asset_id": "BG", "start": [0, 0, 1.04], "end": [-0.01, 0, 1.08]},
        {"asset_id": "FG", "start": [0.02, 0, 1.12], "end": [-0.02, 0, 1.12]}]
    data["shots"][1]["layers"] = [
        {"asset_id": "BG", "start": [0.01, 0, 1.10], "end": [0, 0, 1.04]},
        {"asset_id": "FG", "start": [-0.02, 0, 1.14], "end": [0.02, 0, 1.14]}]
    for shot in data["shots"]:
        shot["review_status"] = "approved"
        shot["notes"] = "程序测试预设，不代表用户认可实际创作画面"
    write_json(root / "project.json", data)
    export_storyboard(root)
    planning_packet(root)
    atomic_text(root / "planning/handoff.md", "# 技术测试交接\n\n"
                "这是 2 个 5 秒几何测试镜头，无旁白；时长为 provisional。\n"
                "背景与透明前景为程序素材，用于验证稳定性、局部重渲染和文件打包。\n"
                "审核标记只适用于测试预设，不代表真实美术或故事已验收。\n")
    return {"project": str(root), "shots": 2, "purpose": "synthetic render QA"}
