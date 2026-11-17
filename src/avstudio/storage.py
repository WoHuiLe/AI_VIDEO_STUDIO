"""Project-local paths, atomic writes and stable file identifiers."""

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path


class StudioError(ValueError):
    pass


def local(root: Path, relative: str) -> Path:
    """Reject absolute paths, traversal and symlinks leaving the project."""
    path = Path(relative)
    if path.is_absolute() or path.drive or not relative:
        raise StudioError(f"需要项目内相对路径：{relative}")
    target = (root / path).resolve()
    if not target.is_relative_to(root.resolve()):
        raise StudioError(f"路径超出项目：{relative}")
    return target


def identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise StudioError("编号须为 1–64 个字母、数字、下划线或连字符")
    return value


def sha256(path: Path) -> str:
    def calculate():
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
    return retry_file_io(calculate)


def retry_file_io(operation):
    import time
    for attempt in range(9):
        try:
            return operation()
        except PermissionError:
            if os.name != "nt" or attempt == 8:
                raise
            time.sleep(min(.01 * 2**attempt, .1))


def read_text_file(path, encoding="utf-8"):
    return retry_file_io(lambda: path.read_text(encoding=encoding))


def replace_file(source, target):
    """Allow short Windows reader/indexer sharing locks to clear, still atomic."""
    import time
    for attempt in range(9):
        try:
            os.replace(source, target)
            return
        except PermissionError as exc:
            if os.name != "nt" or getattr(exc, "winerror", None) not in {5, 32, 33} or attempt == 8:
                raise
            time.sleep(min(.01 * 2**attempt, .1))


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".writing-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
        replace_file(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_json(path: Path):
    return json.loads(read_text_file(path, encoding="utf-8-sig"))


def write_json(path: Path, data) -> None:
    atomic_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def load_project(root: Path) -> dict:
    data = read_json(root / "project.json")
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise StudioError("不支持的项目版本")
    return data


def event(root: Path, action: str, details) -> None:
    from datetime import datetime, timezone

    log = local(root, "work/events.jsonl")
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(),
                                 "action": action, "details": details}, ensure_ascii=False) + "\n")
