"""Explicit, bounded local-folder import with stale-scan detection."""
import io
import re
import secrets
import shutil
import stat
import tempfile
import time
from pathlib import Path
from PIL import Image, ImageOps
from .production import digest
from .project import image_info
from .storage import StudioError, atomic_text, event, load_project, sha256


def has_link(path):
    # Windows junctions also redirect traversal; is_symlink alone misses them.
    return any(p.is_symlink() or getattr(p.lstat(), "st_file_attributes", 0) &
               getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0) for p in [path, *path.parents])


def unchanged(row):
    path = row["path"]
    return (not has_link(path) and path.stat().st_size <= 40 * 1024**2
            and sha256(path) == row["hash"])


class FolderImports:
    def __init__(self, production):
        self.production = production
        self.scans = {}

    def scan(self, root, folder):
        production = self.production
        production.idle(root)
        if not production.approved(root, "storyboard"):
            raise StudioError("请先确认分镜，再扫描配图")
        directory = Path(folder.strip().strip('"')).expanduser()
        if not directory.is_absolute() or has_link(directory):
            raise StudioError("请输入本机图片文件夹的完整路径，不使用符号链接")
        directory = directory.resolve(strict=True)
        if not directory.is_dir() or directory == Path(directory.anchor):
            raise StudioError("请选择存放配图的文件夹，不能是磁盘根目录")
        plan = production.plan(root)
        project = load_project(root)
        mapping = production.mapping(root)
        ids = [s["shot_id"] for s in plan["shots"]]
        rows, total = [], 0
        for path in directory.iterdir():
            if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                continue
            if len(rows) >= 200:
                raise StudioError("文件夹超过 200 张图，请分批整理后导入")
            row = {"name": path.name, "shot_id": None, "error": None, "warnings": []}
            rows.append(row)
            if has_link(path) or not path.is_file() or path.resolve().parent != directory:
                row["error"] = "不读取链接或非普通文件"
                continue
            size = path.stat().st_size
            total += size
            if size > 40 * 1024**2 or total > 200 * 1024**2:
                raise StudioError("图片单张限 40MB，本批合计限 200MB")
            matches = [sid for sid in ids if re.fullmatch(re.escape(sid) + r"(?:[ _-](?!fg(?:[ _-]|$)|foreground(?:[ _-]|$)).*)?", path.stem, re.I)]
            if len(matches) != 1:
                row["error"] = "文件名未匹配镜头编号（透明前景请单独上传）"
                continue
            row["shot_id"] = matches[0]
            try:
                info = image_info(path)
                with Image.open(path) as image:
                    if image.convert("RGBA").getchannel("A").getextrema()[0] != 255:
                        raise StudioError("本轮只导入不透明完整图；透明前景请单独上传")
                row.update(width=info["width"], height=info["height"], path=path, hash=sha256(path))
                if abs(info["width"] / info["height"] - project["width"] / project["height"]) > .03:
                    row["warnings"].append("比例不同，渲染时会裁切")
                if info["width"] < project["width"] or info["height"] < project["height"]:
                    row["warnings"].append("低于目标分辨率")
                entry = mapping.get(matches[0], {})
                if entry.get("background"):
                    row["warnings"].append("将替换当前完整图绑定，原文件保留")
                for aid in entry.get("foregrounds", []):
                    asset = project["assets"][aid]
                    if (asset["width"], asset["height"]) != (info["width"], info["height"]):
                        raise StudioError("与已有透明前景画布不同，请先整理该镜头")
            except (OSError, ValueError, Image.DecompressionBombError) as exc:
                row["error"] = str(exc) if isinstance(exc, StudioError) else "图片无法解码"
        for row in rows:
            if row["shot_id"] and sum(r["shot_id"] == row["shot_id"] for r in rows) > 1:
                row["error"] = "同编号有多个文件，请保留一张后重新扫描"
        rows.sort(key=lambda r: (ids.index(r["shot_id"]) if r["shot_id"] in ids else len(ids), r["name"].casefold()))
        self.scans = {k: v for k, v in self.scans.items() if time.monotonic() - v["created"] < 1800}
        while len(self.scans) >= 10:
            self.scans.pop(next(iter(self.scans)))
        token = secrets.token_urlsafe(24)
        self.scans[token] = {"root": root, "created": time.monotonic(), "revision": digest(plan), "rows": rows}
        return {"scan_id": token, "rows": [{k: v for k, v in row.items() if k not in {"path", "hash"}} for row in rows],
                "ready": sum(not r["error"] for r in rows),
                "missing": [sid for sid in ids if not any(r["shot_id"] == sid and not r["error"] for r in rows)]}

    def get(self, root, token):
        scan = self.scans.get(token)
        if not scan or scan["root"] != root or time.monotonic() - scan["created"] > 1800:
            raise StudioError("扫描已失效，请重新扫描文件夹")
        if scan["revision"] != digest(self.production.plan(root)):
            raise StudioError("分镜已变化，请重新扫描")
        return scan

    def thumbnail(self, root, token, index):
        scan = self.get(root, token)
        if not 0 <= index < len(scan["rows"]):
            raise StudioError("图片编号无效")
        row = scan["rows"][index]
        if row["error"] or not unchanged(row):
            raise StudioError("图片不可预览或已变化，请重新扫描")
        with Image.open(row["path"]) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((480, 270))
            stream = io.BytesIO()
            image.save(stream, "JPEG", quality=80)
            return stream.getvalue()

    def confirm(self, root, token):
        self.production.idle(root)
        scan = self.get(root, token)
        rows = [r for r in scan["rows"] if not r["error"]]
        if not rows:
            raise StudioError("没有可导入的图片，请检查编号和重复文件")
        # Snapshot manifests only; content-addressed source copies are immutable.
        names = ["project.json", "planning/shot_assets.json", "planning/submission.json", "planning/storyboard.csv"]
        originals = {name: (root / name).read_bytes() if (root / name).exists() else None for name in names}
        with tempfile.TemporaryDirectory(prefix="avstudio-batch-") as temporary:
            copies = []
            for index, row in enumerate(rows):
                source = row["path"]
                if not unchanged(row):
                    raise StudioError("扫描后图片发生变化，请重新扫描")
                target = Path(temporary) / f"{index}{source.suffix}"
                shutil.copyfile(source, target)
                if sha256(target) != row["hash"]:
                    raise StudioError("图片复制时发生变化，请重新扫描")
                copies.append((row["shot_id"], target))
            try:
                for shot_id, target in copies:
                    self.production.bind(root, shot_id, "background", target)
            except Exception:
                for name, content in originals.items():
                    if content is None:
                        (root / name).unlink(missing_ok=True)
                    else:
                        atomic_text(root / name, content.decode("utf-8"))
                event(root, "batch_import_rollback", {"scan_id": token})
                raise
        self.scans.pop(token, None)
        event(root, "batch_import", {"shots": [r["shot_id"] for r in rows]})
        return len(rows)
