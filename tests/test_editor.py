import copy
import json
import zipfile
import pytest
from avstudio.storage import load_project, read_json, write_json
from avstudio.project import require_valid
from avstudio.render import signature, render_shot
from avstudio.scenes import commands, raster
from test_production import web, start, action, await_idle, upload, png, plan_fixture
from test_web import request


def demo(web):
    status,_,raw=request(web,'/api/demo',{'request_id':'a'*32})
    assert status==201
    return json.loads(raw)


def edit(web,item,patch=None,operation='edit',sid='S001'):
    return request(web,f"/api/projects/{item['id']}/editor",{'revision':item['editor']['revision'],
        'shot_id':sid,'operation':operation,'patch':json.dumps(patch or {})})


def test_workspace_and_legacy_routes(web):
    status,_,raw=request(web,'/')
    assert status==200 and '镜头时间线' in raw.decode() and '配音面板' not in raw.decode()
    for path in ['/studio.css','/studio.js','/classic']:
        assert request(web,path)[0]==200


def test_demo_is_idempotent_local_and_scene_data_is_real(web):
    item=demo(web);again=demo(web)
    assert item['id']==again['id'] and item['workflow']['ready_count']==3
    assert not item.get('active_job') and not item['assets']
    data=require_valid(web[0].project(item['id']))
    assert len(data['shots'])==3
    status,_,raw=request(web,f"/api/projects/{item['id']}/scene?shot_id=S002")
    frames=json.loads(raw)['frames']
    assert status==200 and len(frames)==round(4*data["fps"]) and frames[0]!=frames[30]
    assert frames[0]==commands(data['shots'][1]['scene'],0,'static')


def test_local_edit_preserves_other_shots_and_has_persistent_undo_redo(web):
    item=demo(web);root=web[0].project(item['id']);before=load_project(root)
    status,_,raw=edit(web,item,{'duration_s':3,'scene':{'palette':'warm','rain':.2,'walk':True,'lamp':.5}})
    result=json.loads(raw)
    assert status==200 and result['editor']['can_undo']
    after=load_project(root)
    assert after['shots'][1:]==before['shots'][1:]
    assert after['shots'][0]['duration_s']==3
    # New object simulates a server restart without losing edit history.
    from avstudio.editor import Editor
    assert Editor(web[0].production).view(root)['can_undo']
    status,_,raw=edit(web,result,operation='undo');undone=json.loads(raw)
    assert status==200 and load_project(root)['shots']==before['shots']
    assert undone['editor']['can_redo']
    status,_,raw=edit(web,undone,operation='redo')
    assert status==200 and load_project(root)['shots'][0]['duration_s']==3


def test_stale_or_invalid_edit_does_not_mutate_project(web):
    item=demo(web);root=web[0].project(item['id'])
    assert edit(web,item,{'duration_s':2})[0]==200
    before={p:(root/p).read_bytes() for p in ['project.json','planning/director.json','work/editor.json']}
    assert edit(web,item,{'duration_s':7})[0]==400
    latest=web[0].detail(item['id'])
    for patch in [{'duration_s':float('nan')},{'scene':{'palette':'bad'}},{'order':['S001','S001','S003']},{'unknown':1}]:
        assert edit(web,latest,patch)[0]==400
        assert before=={p:(root/p).read_bytes() for p in before}


def test_reorder_and_undo_preserve_scene_bindings(web):
    item=demo(web)
    status,_,raw=edit(web,item,{'order':['S003','S001','S002']})
    result=json.loads(raw)
    assert status==200 and [s['shot_id'] for s in result['workflow']['shots']]==['S003','S001','S002']
    assert edit(web,result,operation='undo')[0]==200
    assert [s['shot_id'] for s in load_project(web[0].project(item['id']))['shots']]==['S001','S002','S003']


def test_image_replacement_can_be_undone_without_deleting_sources(web):
    item=start(web,scope='images');action(web,item,'approve_storyboard')
    assert upload(web,item)[0]==200
    before=web[0].detail(item['id']);root=web[0].project(item['id'])
    original=web[0].production.mapping(root)
    assert upload(web,item,content=png(color='blue'))[0]==200
    current=web[0].detail(item['id']);assert current['editor']['can_undo']
    assert edit(web,current,operation='undo')[0]==200
    assert web[0].production.mapping(root)==original
    assert len(load_project(root)['assets'])==2


def test_scene_motion_changes_cache_and_frames(web):
    item=demo(web);data=load_project(web[0].project(item['id']));shot=data['shots'][0]
    key=signature(data,shot)
    shot['motion']='push_in'
    assert signature(data,shot)!=key
    assert commands(shot['scene'],1,'static')!=commands(shot['scene'],1,'push_in')
    assert raster(shot['scene'],0,(160,90)).tobytes()!=raster(shot['scene'],.3,(160,90)).tobytes()


def test_scene_delivery_decodes_and_history_survives_approval(web):
    item=demo(web);root=web[0].project(item['id'])
    # Keep the real encode test small; same command stream as full resolution.
    data=load_project(root);data.update(width=160,height=90,fps=10);write_json(root/'project.json',data)
    item=web[0].detail(item['id'])
    status,_,raw=edit(web,item,{'duration_s':.2});item=json.loads(raw);assert status==200
    for sid in ['S002','S003']:
        status,_,raw=edit(web,item,{'duration_s':.2},sid=sid);item=json.loads(raw);assert status==200
    assert action(web,item,'approve_artwork')[0]==200
    assert web[0].detail(item['id'])['editor']['can_undo']
    assert action(web,item,'deliver')[0]==200
    done=await_idle(web,item['id']);assert done['status']=='complete'
    assert done['editor']['can_undo']
    with zipfile.ZipFile(root/done['delivery_file']) as archive:
        assert archive.testzip() is None
        assert sum(name.endswith('.mp4') for name in archive.namelist())==4


def test_comparison_uses_previous_frame_and_rejects_stale_revision(web):
    item=demo(web)
    status,_,raw=edit(web,item,{'scene':{'palette':'warm','rain':0,'walk':True,'lamp':1}})
    assert status==200
    current=json.loads(raw)
    url=f"/api/projects/{item['id']}/comparison?shot_id=S001&t=0.2&revision="
    status,headers,image=request(web,url+current['editor']['revision'])
    assert status==200 and headers['Content-Type']=='image/png' and image.startswith(b'\x89PNG')
    assert request(web,url+item['editor']['revision'])[0]==400


def test_active_job_blocks_edits_and_rejects_untrusted_fields(web):
    item=demo(web);root=web[0].project(item['id'])
    web[0].production.update(root,active_job='test-job')
    assert edit(web,item,{'duration_s':5})[0]==400
    web[0].production.update(root,active_job=None)
    assert edit(web,item,{'scene':{'palette':'night','rain':.4,'walk':True,'lamp':1,'code':'execute'}})[0]==400


def test_export_scope_can_change_without_resetting_plan_or_assets(web):
    item=demo(web);root=web[0].project(item['id']);before=web[0].production.plan(root)
    status,_,raw=request(web,f"/api/projects/{item['id']}/actions",{'action':'set_scope','scope':'images'})
    assert status==200 and json.loads(raw)['brief']['scope']=='images'
    assert load_project(root)['scope']=='images' and web[0].production.plan(root)==before
    assert request(web,f"/api/projects/{item['id']}/actions",{'action':'set_scope','scope':'invalid'})[0]==400


def test_noop_save_does_not_revoke_artwork_approval(web):
    item=demo(web);assert action(web,item,'approve_artwork')[0]==200
    current=web[0].detail(item['id']);before=current['workflow']['approvals']
    status,_,raw=edit(web,current,{'duration_s':4})
    assert status==200 and json.loads(raw)['workflow']['approvals']==before
