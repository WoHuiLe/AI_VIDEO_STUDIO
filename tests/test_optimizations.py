import io
import json
import threading
import zipfile

import pytest
from PIL import Image

from avstudio.delivery import package
from avstudio.render import frame, geometry, render_shot
from avstudio.storage import StudioError, load_project, read_json, write_json
from test_production import web, start, action, upload, png, await_idle
from test_web import request


@pytest.mark.parametrize("width,height", [(1080,1920),(1920,1080),(1080,1080),(320,240)])
def test_preview_bounds_long_edge(width,height):
    size=geometry({"width":width,"height":height},True)
    assert max(size)<=640 and all(v%2==0 for v in size)
    assert abs(size[0]/size[1]-width/height)<0.01


def test_full_resolution_sampling_has_no_exposed_canvas():
    source=Image.new("RGBA",(800,400),"#557744")
    result=frame([source],[{"start":[0,0,1.2],"end":[0.02,0,1.2]}],(160,80),0.5)
    assert result.size==(160,80)
    assert result.getextrema()==((85,85),(119,119),(68,68))


def test_storyboard_change_revokes_approval_until_new_plan(web):
    item=start(web);action(web,item,"approve_storyboard");upload(web,item)
    status,_,_=request(web,f"/api/projects/{item['id']}/feedback",{"note":"需要更克制的画面","stage":"storyboard","decision":"changes"})
    assert status==200
    view=web[0].detail(item["id"])
    assert view["workflow"]["needs_revision"] and "storyboard" not in view["workflow"]["approvals"]
    assert action(web,item,"approve_storyboard")[0]==400
    action(web,item,"plan")
    result=await_idle(web,item["id"])
    assert not result["workflow"]["needs_revision"]
    assert action(web,item,"approve_storyboard")[0]==200


def test_feedback_does_not_copy_existing_media(web,monkeypatch):
    item=start(web);action(web,item,"approve_storyboard");upload(web,item)
    root=web[0].project(item["id"])
    originals={key:asset["path"] for key,asset in load_project(root)["assets"].items()}
    import avstudio.web.server as server
    copied=[];original_copy=server.shutil.copyfile
    def tracked(source,target,*args,**kwargs):
        copied.append(str(source));return original_copy(source,target,*args,**kwargs)
    monkeypatch.setattr(server.shutil,"copyfile",tracked)
    assert request(web,f"/api/projects/{item['id']}/feedback",{"note":"请保留角色参考","decision":"note"})[0]==200
    assert not any("assets" in path for path in copied)
    assert all((root/path).exists() for path in originals.values())
    assert load_project(root)["assets"].keys()==originals.keys()


def test_remove_foreground_retains_original_file(web):
    item=start(web);action(web,item,"approve_storyboard");upload(web,item)
    upload(web,item,"foreground",png("RGBA",color=(40,60,10,80)))
    root=web[0].project(item["id"])
    layer=web[0].detail(item["id"])["workflow"]["shots"][0]["foregrounds"][0]
    status,_,_=request(web,f"/api/projects/{item['id']}/actions",{"action":"remove_foreground","shot_id":"S001","asset_id":layer["asset_id"]})
    assert status==200 and (root/layer["path"]).exists()
    assert len(load_project(root)["shots"][0]["layers"])==1


def test_polls_use_etag_and_change_after_feedback(web):
    item=start(web)
    path=f"/api/projects/{item['id']}"
    status,headers,body=request(web,path)
    assert status==200 and headers.get("ETag")
    status,_,cached=request(web,path,headers={"If-None-Match":headers["ETag"]})
    assert status==304 and cached==b""
    request(web,path+"/feedback",{"note":"新增要求","decision":"note"})
    assert request(web,path,headers={"If-None-Match":headers["ETag"]})[0]==200


def test_delivery_snapshot_clears_transient_job_and_preserves_attachments(web):
    item=start(web,scope="images");action(web,item,"approve_storyboard");upload(web,item)
    request(web,f"/api/projects/{item['id']}/feedback",{"note":"附参考资料"},[("supplements","reference.txt",b"a reference")])
    root=web[0].project(item["id"])
    meta=read_json(root/"planning/submission.json");meta.update(active_job="transient",status="working");write_json(root/"planning/submission.json",meta)
    path=package(root)
    with zipfile.ZipFile(path) as archive:
        exported=json.loads(archive.read("planning/submission.json"))
        assert exported["active_job"] is None and exported["status"]!="working"
        assert all(record["path"] in archive.namelist() for record in exported["files"])
        import hashlib
        for entry in json.loads(archive.read("PACKAGE_MANIFEST.json")):
            assert hashlib.sha256(archive.read(entry["path"])).hexdigest()==entry["sha256"]
    assert read_json(root/"planning/submission.json")["active_job"]=="transient"


def test_unfinished_outputs_are_not_presented(web):
    item=start(web);root=web[0].project(item["id"])
    (root/"output/.writing-unfinished.zip").write_bytes(b"not ready")
    assert not any(f["name"].startswith(".writing-") for f in web[0].detail(item["id"])["outputs"])


def test_cancelled_render_does_not_publish_file(web):
    item=start(web);action(web,item,"approve_storyboard");upload(web,item)
    root=web[0].project(item["id"]);data=load_project(root)
    cancelled=threading.Event();cancelled.set()
    with pytest.raises(StudioError,match="取消"):
        render_shot(root,data,data["shots"][0],cancelled=cancelled)
    assert not list((root/"work/shots").glob("*.mp4"))


def test_reading_inbox_does_not_interrupt_live_jobs(tmp_path):
    from avstudio.web.server import Desk
    desk=Desk(tmp_path)
    item=desk.submit({"title":"test","script":"原文"},[])
    root=desk.project(item["id"])
    write_json(root/"work/jobs/live.json",{"id":"live","action":"plan","status":"running"})
    meta=read_json(root/"planning/submission.json");meta.update(status="working",active_job="live");write_json(root/"planning/submission.json",meta)
    observer=Desk(tmp_path)
    assert observer.detail(item["id"])["active_job"]=="live"
    assert read_json(root/"work/jobs/live.json")["status"]=="running"


def test_workspace_lease_prevents_duplicate_workers(tmp_path):
    from avstudio.runtime import WorkspaceLease
    with WorkspaceLease(tmp_path):
        with pytest.raises(StudioError,match="已经"):
            with WorkspaceLease(tmp_path):
                pass
    with WorkspaceLease(tmp_path):
        pass
