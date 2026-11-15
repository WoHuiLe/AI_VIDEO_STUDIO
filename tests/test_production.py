import copy
import io
import threading
import time
import zipfile

import pytest
from PIL import Image

from avstudio.planner import validate_plan
from avstudio.storage import StudioError, load_project, read_json, write_json
from avstudio.web.server import Desk, DeskServer
from test_web import brief, request


def plan_fixture():
    return {"summary": "用窗边与书页表达清晨。", "visual_style": "自然光绘本", "character_notes": "不新增人物",
            "shots": [{"shot_id": "S001", "segment_ids": ["SEG001", "SEG002"],
                       "narrative_purpose": "建立场景", "visual_description": "窗边的一本书，前景有树叶",
                       "shot_size": "近景", "layer_plan": "完整背景与可选透明树叶",
                       "image_prompt": "自然光绘本，窗边书页，保持构图，无文字水印",
                       "motion": "push_in", "duration_s": 0.25}]}


def fixture_planner(project, brief, feedback, work, cancelled, progress):
    progress("测试执行器正在生成结构化分镜")
    return validate_plan(plan_fixture(), project)


@pytest.fixture
def web(tmp_path):
    desk = Desk(tmp_path, planner=fixture_planner)
    server = DeskServer(("127.0.0.1", 0), desk)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield desk, server.server_address[1]
    server.shutdown(); server.server_close(); thread.join(timeout=5)


def await_idle(web, project_id):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        result = web[0].detail(project_id)
        if not result.get("active_job"):
            return result
        time.sleep(0.02)
    pytest.fail("测试任务未结束")


def start(web, **extra):
    result = request(web, "/api/projects", brief(start_now="1", **extra))
    assert result[0] == 201
    import json
    project = __import__("json").loads(result[2])
    return await_idle(web, project["id"])


def action(web, item, name):
    status, _, raw = request(web, f"/api/projects/{item['id']}/actions", {"action": name})
    import json
    return status, json.loads(raw)


def png(mode="RGB", size=(160, 90), color="green"):
    stream=io.BytesIO();Image.new(mode,size,color).save(stream,format="PNG");return stream.getvalue()


def upload(web, item, role="background", content=None):
    return request(web, f"/api/projects/{item['id']}/shot-assets", {"shot_id":"S001","role":role},
                   [("image","art.png",content or png())])


def test_full_web_image_delivery_has_real_zip(web):
    item = start(web, scope="images")
    assert item["status"] == "review" and item["workflow"]["has_plan"]
    assert action(web,item,"approve_storyboard")[0] == 200
    assert upload(web,item)[0] == 200
    assert action(web,item,"approve_artwork")[0] == 200
    assert action(web,item,"deliver")[0] == 200
    done = await_idle(web,item["id"])
    assert done["status"] == "complete"
    root = web[0].project(item["id"])
    path = root / done["delivery_file"]
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        assert "project.json" in archive.namelist()
    assert done["workflow"]["jobs"][0]["status"] == "succeeded"


def test_full_web_layered_motion_delivery(web):
    item = start(web, scope="shots")
    action(web,item,"approve_storyboard")
    upload(web,item)
    assert upload(web,item,"foreground",png("RGBA",color=(120,40,10,60)))[0] == 200
    action(web,item,"approve_artwork")
    action(web,item,"deliver")
    done = await_idle(web,item["id"])
    assert done["status"] == "complete"
    assert any(f["name"].endswith(".mp4") for f in done["outputs"])
    assert len(load_project(web[0].project(item["id"]))["shots"][0]["layers"]) == 2


def test_layer_scope_cannot_claim_flat_image_is_layered(web):
    item = start(web, scope="layers")
    action(web,item,"approve_storyboard");upload(web,item)
    status, result = action(web,item,"approve_artwork")
    assert status == 400 and "分层" in result["error"]


def test_initial_approval_and_invalid_layer_are_rejected(web):
    import json
    item=json.loads(request(web,"/api/projects",brief())[2])
    assert action(web,item,"approve_storyboard")[0] == 400
    item = start(web)
    action(web,item,"approve_storyboard")
    upload(web,item)
    assert upload(web,item,"foreground",png())[0] == 400
    assert upload(web,item,"foreground",png("RGBA",(100,100),(0,0,0,60)))[0] == 400


def test_replacement_invalidates_approval_and_retains_old_asset(web):
    item = start(web)
    action(web,item,"approve_storyboard");upload(web,item);action(web,item,"approve_artwork")
    root=web[0].project(item["id"])
    before=load_project(root)
    assert upload(web,item,content=png(color="blue"))[0] == 200
    assert "artwork" not in web[0].detail(item["id"])["workflow"]["approvals"]
    assert action(web,item,"deliver")[0] == 400
    for asset in before["assets"].values(): assert (root/asset["path"]).exists()


def test_failed_job_and_retry_are_truthful(web):
    def failing(*args): raise StudioError("测试网络错误")
    web[0].production.planner=failing
    item=start(web)
    assert item["status"] == "error" and "测试网络错误" in item["workflow"]["error"]
    web[0].production.planner=fixture_planner
    assert action(web,item,"plan")[0] == 200
    assert await_idle(web,item["id"])["status"] == "review"


def test_cancel_and_duplicate_clicks_do_not_duplicate_work(web):
    entered=threading.Event()
    def waiting(project,brief,feedback,work,cancelled,progress):
        entered.set();cancelled.wait(5);raise StudioError("任务已取消")
    web[0].production.planner=waiting
    import json
    item=json.loads(request(web,"/api/projects",brief())[2])
    first=action(web,item,"plan")[1];assert entered.wait(2)
    again=action(web,item,"plan")[1]
    assert first["active_job"] == again["active_job"]
    assert action(web,item,"cancel")[0] == 200
    done=await_idle(web,item["id"])
    assert done["workflow"]["jobs"][0]["status"] == "cancelled"


def test_restart_recovers_running_job(tmp_path):
    desk=Desk(tmp_path,planner=fixture_planner)
    item=desk.submit(brief(),[]);root=desk.project(item["id"])
    job={"id":"abc","action":"plan","status":"running"}
    write_json(root/"work/jobs/abc.json",job)
    meta=read_json(root/"planning/submission.json");meta.update(active_job="abc",status="working");write_json(root/"planning/submission.json",meta)
    restored=Desk(tmp_path,planner=fixture_planner)
    assert restored.detail(item["id"])["status"] == "error"
    assert read_json(root/"work/jobs/abc.json")["status"] == "interrupted"


@pytest.mark.parametrize("change", ["duplicate", "unknown_segment", "uncovered", "bad_motion", "bad_duration"])
def test_planner_output_is_validated(change):
    plan=plan_fixture();project={"segments":[{"segment_id":"SEG001"},{"segment_id":"SEG002"}]}
    if change=="duplicate":plan["shots"].append(copy.deepcopy(plan["shots"][0]))
    if change=="unknown_segment":plan["shots"][0]["segment_ids"]=["UNKNOWN"]
    if change=="uncovered":plan["shots"][0]["segment_ids"]=["SEG001"]
    if change=="bad_motion":plan["shots"][0]["motion"]="shell command"
    if change=="bad_duration":plan["shots"][0]["duration_s"]=float("nan")
    with pytest.raises(StudioError):validate_plan(plan,project)
