"""Command line entrypoint. Local files only; no implicit paid API calls."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .assets import apply_mask, check_assets, contact_sheet
from .delivery import package
from .media import doctor, export_srt, import_timeline, inspect_media
from .project import (add_shot, attach_audio, export_assets, export_storyboard, import_storyboard,
                      init_project, planning_packet, register_asset, require_valid)
from .render import assemble, render_project
from .storage import StudioError, identifier, write_json


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="avstudio", description="文案、素材、镜头与剪映交接工具")
    commands = p.add_subparsers(dest="command", required=True)
    q = commands.add_parser("doctor", help="只读检查 Python、FFmpeg 和磁盘")
    q.add_argument("--output", type=Path)
    q = commands.add_parser("mask", help="用已有灰度蒙版提取透明 PNG；不自动抠图")
    q.add_argument("image", type=Path)
    q.add_argument("mask", type=Path)
    q.add_argument("output", type=Path)
    q = commands.add_parser("init", help="保留原文，建立项目及段落编号")
    q.add_argument("project", type=Path)
    q.add_argument("--script", type=Path, required=True)
    q.add_argument("--title", required=True)
    q.add_argument("--scope", choices=["images", "layers", "shots", "roughcut"], default="images")
    q = commands.add_parser("inspect", help="检查媒体和完整解码，不代替观感验收")
    q.add_argument("file", type=Path)
    q.add_argument("--probe-only", action="store_true")
    q.add_argument("--output", type=Path)
    for name, help_text in [("validate", "验证数据、引用、时间和文件哈希"),
                            ("plan", "生成跨 AI 视觉设计任务书"),
                            ("export-storyboard", "导出分镜 CSV"),
                            ("export-assets", "导出真实素材清单 CSV"),
                            ("srt", "从已校准镜头导出待审核字幕草稿"),
                            ("check-assets", "检查实际图片尺寸和构图裁切风险"),
                            ("contact-sheet", "生成素材审阅联系表")]:
        q = commands.add_parser(name, help=help_text)
        q.add_argument("project", type=Path)
    q = commands.add_parser("import-storyboard", help="从 CSV 导入已有镜头编辑")
    q.add_argument("project", type=Path)
    q.add_argument("file", type=Path)
    q = commands.add_parser("asset", help="不可变保存图片并登记实际尺寸和哈希")
    q.add_argument("project", type=Path)
    q.add_argument("file", type=Path)
    q.add_argument("--id", required=True)
    q.add_argument("--source", required=True)
    q.add_argument("--usage-terms", default="unspecified")
    q = commands.add_parser("audio", help="导入真实录音或手工 TTS 并使旧校准失效")
    q.add_argument("project", type=Path)
    q.add_argument("file", type=Path)
    q = commands.add_parser("add-shot", help="创建明确叙事目的的镜头；时长暂定")
    q.add_argument("project", type=Path)
    q.add_argument("--id", required=True)
    q.add_argument("--segments", required=True, help="段落编号，分号分隔")
    q.add_argument("--asset", required=True)
    q.add_argument("--duration", required=True, type=float)
    q.add_argument("--description", required=True)
    q.add_argument("--purpose", required=True)
    q = commands.add_parser("timeline", help="导入人工复核的真实旁白时间 JSON")
    q.add_argument("project", type=Path)
    q.add_argument("file", type=Path)
    q.add_argument("--confirmed", action="store_true")
    q = commands.add_parser("render", help="独立镜头渲染；相同参数复用缓存")
    q.add_argument("project", type=Path)
    q.add_argument("--preview", action="store_true")
    q.add_argument("--shot")
    q = commands.add_parser("assemble", help="顺序直切无字幕粗剪")
    q.add_argument("project", type=Path)
    q.add_argument("--preview", action="store_true")
    q = commands.add_parser("package", help="打包策划/素材或已审核镜头")
    q.add_argument("project", type=Path)
    q.add_argument("--renders", action="store_true")
    q = commands.add_parser("demo", help="建立纯程序测试素材项目，不消耗图像额度")
    q.add_argument("project", type=Path)
    q = commands.add_parser("web", help="启动本机制作资料提交网页")
    q.add_argument("--workspace", type=Path, default=Path.cwd())
    q.add_argument("--port", type=int, default=8765)
    q = commands.add_parser("inbox", help="读取网页提交的待处理项目与反馈")
    q.add_argument("--workspace", type=Path, default=Path.cwd())
    return p


def execute(args):
    command = args.command
    root = args.project.resolve() if hasattr(args, "project") else None
    if command == "doctor":
        result = doctor()
    elif command == "web":
        from .web.server import serve
        serve(args.workspace, args.port)
        result = {"status": "stopped"}
    elif command == "inbox":
        from .web.server import Desk
        desk = Desk(args.workspace)
        result = [{**item, "project_path": str(desk.project(item["id"]))}
                  for item in desk.summaries() if item["status"] in {"queued", "feedback"}]
    elif command == "inspect":
        result = inspect_media(args.file, not args.probe_only)
    elif command == "mask":
        result = str(apply_mask(args.image, args.mask, args.output))
    elif command == "check-assets":
        result = check_assets(root)
    elif command == "contact-sheet":
        result = str(contact_sheet(root))
    elif command == "init":
        result = init_project(root, args.script, args.title, args.scope)
    elif command == "validate":
        data = require_valid(root)
        result = {"status": "PASS", "shots": len(data["shots"]), "assets": len(data["assets"])}
    elif command == "plan":
        result = str(planning_packet(root))
    elif command == "asset":
        result = register_asset(root, args.file, args.id, args.source, args.usage_terms)
    elif command == "audio":
        attach_audio(root, args.file)
        result = {"status": "imported", "alignment": "needs_review"}
    elif command == "add-shot":
        result = add_shot(root, args.id, args.segments.split(";"), args.asset,
                          args.duration, args.description, args.purpose)
    elif command == "export-storyboard":
        result = str(export_storyboard(root))
    elif command == "export-assets":
        result = str(export_assets(root))
    elif command == "import-storyboard":
        result = {"imported": import_storyboard(root, args.file)}
    elif command == "timeline":
        result = {"aligned": import_timeline(root, args.file, args.confirmed)}
        export_storyboard(root)
    elif command == "srt":
        result = str(export_srt(root))
    elif command == "render":
        result = render_project(root, args.preview, args.shot)
    elif command == "assemble":
        result = assemble(root, args.preview)
    elif command == "package":
        result = str(package(root, args.renders))
    elif command == "demo":
        from .demo import create_demo
        result = create_demo(root)
    else:
        raise StudioError("未知命令")
    if command in {"doctor", "inspect"} and args.output:
        write_json(args.output, result)
    return result


def main():
    # Windows console code pages otherwise corrupt Chinese in redirected JSON.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parser().parse_args()
    try:
        result = execute(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.command == "doctor" and any(t["status"] == "FAIL" for t in result["tools"].values()):
            raise SystemExit(1)
    except (StudioError, OSError, KeyError, TypeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        raise SystemExit(1)
