"""Image inspection, contact sheets and explicit mask-based layer preparation."""

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from .project import image_info, require_valid
from .storage import StudioError, local, write_json


def check_assets(root: Path) -> dict:
    data = require_valid(root)
    results = []
    for asset_id, asset in data["assets"].items():
        info = image_info(local(root, asset["path"]))
        issues = []
        if info["width"] < data["width"] or info["height"] < data["height"]:
            issues.append("源图小于输出尺寸；裁切和推近还需要额外余量")
        if abs(info["width"] / info["height"] - data["width"] / data["height"]) > 0.02:
            issues.append("源图与输出比例不同，渲染时会中心裁切，需检查构图")
        results.append({"asset_id": asset_id, **info, "file_integrity": "PASS",
                        "warnings": issues, "visual_review": asset.get("visual_check", "NOT_RUN"),
                        "usage_terms": asset.get("usage_terms", "unspecified")})
    report = {"assets": results, "note": "人脸、手部、叙事和画风由 AI/人工审阅；尺寸检查不替代美术验收"}
    write_json(root / "work/asset-checks.json", report)
    return report


def contact_sheet(root: Path) -> Path:
    data = require_valid(root)
    items = list(data["assets"].items())
    if not items:
        raise StudioError("没有图片素材")
    columns = min(3, len(items))
    # Paginate instead of allocating an unbounded single image.
    paths = []
    for page_start in range(0, len(items), 24):
        page = items[page_start:page_start + 24]
        rows = math.ceil(len(page) / columns)
        canvas = Image.new("RGB", (columns * 340, rows * 230), "#ecebe6")
        draw = ImageDraw.Draw(canvas)
        for index, (aid, asset) in enumerate(page):
            x, y = (index % columns) * 340, (index // columns) * 230
            with Image.open(local(root, asset["path"])) as original:
                image = ImageOps.exif_transpose(original).convert("RGBA")
                image.thumbnail((320, 180), Image.Resampling.LANCZOS)
                canvas.paste(image, (x + 10, y + 10), image)
            draw.text((x + 10, y + 198), f"{aid} / {asset['width']}x{asset['height']}", fill="black")
        path = root / f"work/contact-sheet-{page_start // 24 + 1:02}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(path, quality=92)
        paths.append(path)
    return paths[0]


def apply_mask(image_path: Path, mask_path: Path, output: Path) -> Path:
    """Use a provided mask; never claim automatic semantic segmentation."""
    if output.exists():
        raise StudioError("输出已存在，不覆盖")
    if output.suffix.lower() != ".png":
        raise StudioError("透明图层输出必须使用 .png")
    with Image.open(image_path) as original, Image.open(mask_path) as supplied:
        image = ImageOps.exif_transpose(original).convert("RGBA")
        mask = ImageOps.exif_transpose(supplied).convert("L")
        if image.size != mask.size:
            raise StudioError("蒙版与原图尺寸不同，不能静默拉伸")
        # Preserve existing transparency as well as the supplied selection.
        from PIL import ImageChops
        image.putalpha(ImageChops.multiply(image.getchannel("A"), mask))
        output.parent.mkdir(parents=True, exist_ok=True)
        image.save(output)
    return output
