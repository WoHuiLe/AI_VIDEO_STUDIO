import http.client
import io
import json
import threading
from urllib.parse import quote

import pytest
from PIL import Image

from avstudio.project import require_valid
from avstudio.storage import read_json
from avstudio.web.server import Desk, DeskServer, MAX_BODY


def multipart(fields, files=()):
    boundary = "studio-test-boundary"
    body = bytearray()
    for name, value in fields.items():
        body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for name, filename, content in files:
        body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode())
        body.extend(content)
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    return bytes(body), f"multipart/form-data; boundary={boundary}"


@pytest.fixture
def web(tmp_path):
    desk = Desk(tmp_path)
    server = DeskServer(("127.0.0.1", 0), desk)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield desk, server.server_address[1]
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def request(web, path, fields=None, files=(), method=None, headers=None):
    desk, port = web
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    request_headers = {}
    body = None
    if fields is not None:
        body, kind = multipart(fields, files)
        request_headers = {"Content-Type": kind, "Origin": f"http://127.0.0.1:{port}", "X-Studio-Token": desk.token}
    request_headers.update(headers or {})
    connection.request(method or ("POST" if fields is not None else "GET"), path, body, request_headers)
    response = connection.getresponse()
    status, response_headers, result = response.status, dict(response.getheaders()), response.read()
    connection.close()
    return status, response_headers, result


def brief(**extra):
    return {"title": "新故事 <不是 HTML>", "script": "第一段，保留原文。\n\n第二段，望向远方。",
            "scope": "shots", "style": "绘本电影感", "ratio": "16:9", **extra}


def test_submission_survives_server_recreation_and_builds_real_project(web):
    status, _, body = request(web, "/api/projects", brief(notes="不要过度煽情", must_keep="信封"))
    assert status == 201
    item = json.loads(body)
    root = web[0].project(item["id"])
    project = require_valid(root)
    assert project["title"] == "新故事 <不是 HTML>" and len(project["segments"]) == 2
    assert item["status"] == "queued" and item["outputs"] == []
    assert "不要过度煽情" in (root / "planning/brief.md").read_text(encoding="utf-8")
    assert (root / "planning/visual_task.md").exists()
    recreated = Desk(web[0].workspace)
    assert recreated.detail(item["id"])["script"] == brief()["script"]


def test_original_script_whitespace_is_preserved(web):
    script = "  保留诗句前的空格。\n\n下一行。\n"
    status, _, body = request(web, "/api/projects", brief(script=script))
    assert status == 201
    assert json.loads(body)["script"] == script


def test_upload_image_and_script_file(web):
    image = io.BytesIO()
    Image.new("RGB", (64, 48), "green").save(image, format="PNG")
    status, _, body = request(web, "/api/projects", brief(script="", ratio="9:16"), [
        ("script_file", "文案.txt", "由文件提供的文案。".encode()),
        ("references", "角色参考.png", image.getvalue())])
    assert status == 201
    item = json.loads(body)
    assert item["script"] == "由文件提供的文案。" and len(item["files"]) == 1
    assert item["files"][0]["name"] == "角色参考.png"
    data = require_valid(web[0].project(item["id"]))
    assert (data["width"], data["height"]) == (1080, 1920)


@pytest.mark.parametrize("fields,files", [
    (brief(title=""), []),
    (brief(script=""), []),
    (brief(ratio="invalid"), []),
    (brief(), [("references", "script.exe", b"not allowed")]),
    (brief(), [("references", "fake.png", b"not an image")]),
    (brief(script="different"), [("script_file", "original.txt", b"other text")]),
])
def test_bad_submission_leaves_no_half_project(web, fields, files):
    status, _, _ = request(web, "/api/projects", fields, files)
    assert status == 400
    assert list(web[0].projects.iterdir()) == []


def test_retries_do_not_duplicate_submissions_or_feedback(web):
    data = brief(request_id="a" * 32)
    first = json.loads(request(web, "/api/projects", data)[2])
    second = json.loads(request(web, "/api/projects", data)[2])
    assert first["id"] == second["id"] and len(web[0].summaries()) == 1
    path = f"/api/projects/{first['id']}/feedback"
    note = {"note": "第三个镜头需要更克制", "stage": "storyboard", "decision": "changes", "request_id": "b" * 32}
    one = json.loads(request(web, path, note)[2])
    two = json.loads(request(web, path, note)[2])
    assert len(one["feedback"]) == len(two["feedback"]) == 1
    assert two["status"] == "feedback"


def test_invalid_feedback_does_not_change_existing_project(web):
    created = json.loads(request(web, "/api/projects", brief())[2])
    root = web[0].project(created["id"])
    original = (root / "project.json").read_bytes()
    status, _, _ = request(web, f"/api/projects/{created['id']}/feedback",
                           {"note": "新增参考", "decision": "note"},
                           [("supplements", "bad.png", b"broken")])
    assert status == 400
    assert (root / "project.json").read_bytes() == original
    assert read_json(root / "planning/feedback.json") == []


def test_local_origin_and_token_required(web):
    assert request(web, "/api/projects", brief(), headers={"X-Studio-Token": "wrong"})[0] == 403
    assert request(web, "/api/projects", brief(), headers={"Origin": "https://other.example"})[0] == 403
    assert request(web, "/api/projects", headers={"Host": "other.example"})[0] == 403
    assert web[0].summaries() == []


def test_download_and_video_ranges_cannot_escape_project(web):
    item = json.loads(request(web, "/api/projects", brief())[2])
    prefix = f"/api/projects/{item['id']}/file?path="
    status, headers, content = request(web, prefix + quote("input/script_original.txt"), headers={"Range": "bytes=0-4"})
    assert status == 206 and len(content) == 5 and headers["Content-Range"].startswith("bytes 0-4/")
    assert request(web, prefix + quote("input/../../outside.txt"))[0] == 400
    assert request(web, prefix + quote("../project.json"))[0] == 400
    assert request(web, prefix + quote("input/script_original.txt"), headers={"Range": "bytes=999999-"})[0] == 416


def test_static_page_and_assets_have_correct_types(web):
    status, headers, html = request(web, "/")
    assert status == 200 and "text/html" in headers["Content-Type"]
    assert "镜头时间线" in html.decode() and "studio.js" in html.decode()
    assert request(web, "/app.js")[0] == request(web, "/style.css")[0] == 200
    config = json.loads(request(web, "/api/config")[2])
    assert config["max_upload_bytes"] == MAX_BODY
    assert config["service"] == "avstudio-desk"
