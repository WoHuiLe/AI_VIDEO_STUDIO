import copy
import json
from pathlib import Path
import pytest
from avstudio.storage import StudioError, load_project
from avstudio.taskpacks import rules, storyboard_task
from test_production import web, start, action, plan_fixture, png, await_idle
from test_web import request


def post(web, item, route, fields):
    status, _, raw = request(web, f"/api/projects/{item['id']}/{route}", fields)
    return status, json.loads(raw)


def prepare(web, tmp_path):
    item = start(web, scope='images')
    assert action(web, item, 'approve_storyboard')[0] == 200
    folder = tmp_path / 'art';folder.mkdir()
    (folder / 'S001.png').write_bytes(png())
    return item, folder


def test_portable_task_has_source_requirements_rules_schema_and_example(web):
    item = start(web, scope='images', notes='克制表达')
    status, _, raw = request(web, f"/api/projects/{item['id']}/task-pack?kind=storyboard")
    task = json.loads(raw)['text']
    assert status == 200
    assert rules() in task and '克制表达' in task
    assert all(word in task for word in ['original_script', 'SEG001', 'SEG002', '返回 JSON schema', '结构示例'])
    root = web[0].project(item['id'])
    meta = web[0].production.meta(root)
    from avstudio.taskpacks import project_brief
    assert task == storyboard_task(load_project(root),project_brief(root,load_project(root),meta),[])


def test_paste_import_and_repair_leave_previous_plan_untouched(web):
    item = start(web, scope='images');root=web[0].project(item['id'])
    original=(root/'planning/director.json').read_bytes()
    for text in ['{oops}', '{}', '{"summary":5}', json.dumps({**plan_fixture(),'shots':[{'shot_id':None}]})]:
        status, result=post(web,item,'plan-import',{'plan_text':text})
        assert status == 200 and result['valid'] is False
        assert '校验问题' in result['repair_task']
        assert (root/'planning/director.json').read_bytes() == original
    plan=plan_fixture();plan['summary']='外部设计的新理解'
    status,result=post(web,item,'plan-import',{'plan_text':'```json\n'+json.dumps(plan)+'\n```'})
    assert status==200 and result['workflow']['has_plan']
    assert web[0].production.plan(root)['summary']=='外部设计的新理解'


def test_all_image_prompts_have_shared_style_and_stable_filenames(web):
    item=start(web,scope='images')
    status,_,raw=request(web,f"/api/projects/{item['id']}/task-pack?kind=images")
    text=json.loads(raw)['text']
    assert status==200 and 'S001.png' in text and plan_fixture()['shots'][0]['image_prompt'] in text
    assert plan_fixture()['visual_style'] in text and '不要拼贴' in text


def test_scan_preview_and_confirm_preserve_source(web,tmp_path):
    item,folder=prepare(web,tmp_path);original=(folder/'S001.png').read_bytes()
    status,scan=post(web,item,'folder-scan',{'folder':str(folder)})
    assert status==200 and scan['ready']==1 and scan['missing']==[]
    assert '低于目标分辨率' in scan['rows'][0]['warnings']
    status,headers,thumb=request(web,f"/api/projects/{item['id']}/scan-thumbnail?scan_id={scan['scan_id']}&index=0")
    assert status==200 and headers['Content-Type']=='image/jpeg' and thumb.startswith(b'\xff\xd8')
    assert post(web,item,'folder-confirm',{'scan_id':scan['scan_id']})[0]==400
    status,result=post(web,item,'folder-confirm',{'scan_id':scan['scan_id'],'confirmed':'1'})
    assert status==200 and result['workflow']['ready_count']==1
    assert (folder/'S001.png').read_bytes()==original
    assert action(web,item,'approve_artwork')[0]==200
    assert action(web,item,'deliver')[0]==200
    done=await_idle(web,item['id'])
    assert done['status']=='complete' and (web[0].project(item['id'])/done['delivery_file']).is_file()
    assert post(web,item,'folder-confirm',{'scan_id':scan['scan_id'],'confirmed':'1'})[0]==400


def test_duplicate_unknown_and_foreground_are_not_silently_matched(web,tmp_path):
    item,folder=prepare(web,tmp_path)
    for name in ['s001_other.png','S0010.png','S001_fg.png','random.png']:(folder/name).write_bytes(png())
    status,scan=post(web,item,'folder-scan',{'folder':str(folder)})
    assert status==200 and scan['ready']==0 and scan['missing']==['S001']
    assert sum('同编号' in (r['error'] or '') for r in scan['rows'])==2
    assert post(web,item,'folder-confirm',{'scan_id':scan['scan_id'],'confirmed':'1'})[0]==400


def test_changed_file_and_plan_invalidate_scan(web,tmp_path):
    item,folder=prepare(web,tmp_path)
    _,scan=post(web,item,'folder-scan',{'folder':str(folder)})
    (folder/'S001.png').write_bytes(png(color='blue'))
    assert post(web,item,'folder-confirm',{'scan_id':scan['scan_id'],'confirmed':'1'})[0]==400
    assert not load_project(web[0].project(item['id']))['assets']
    _,scan=post(web,item,'folder-scan',{'folder':str(folder)})
    plan=plan_fixture();plan['summary']='新版'
    post(web,item,'plan-import',{'plan_text':json.dumps(plan)})
    assert post(web,item,'folder-confirm',{'scan_id':scan['scan_id'],'confirmed':'1'})[0]==400


def test_batch_failure_rolls_back_manifests(web,tmp_path,monkeypatch):
    item,folder=prepare(web,tmp_path);root=web[0].project(item['id'])
    plan=plan_fixture();second=copy.deepcopy(plan['shots'][0]);second['shot_id']='S002';plan['shots'].append(second)
    post(web,item,'plan-import',{'plan_text':json.dumps(plan)});action(web,item,'approve_storyboard')
    (folder/'S002.png').write_bytes(png(color='blue'))
    _,scan=post(web,item,'folder-scan',{'folder':str(folder)})
    names=['project.json','planning/shot_assets.json','planning/submission.json','planning/storyboard.csv']
    before={name:(root/name).read_bytes() for name in names}
    bind=web[0].production.bind;calls=[]
    def failing(*args):
        calls.append(1)
        if len(calls)==2:raise StudioError('模拟第二张失败')
        return bind(*args)
    monkeypatch.setattr(web[0].production,'bind',failing)
    assert post(web,item,'folder-confirm',{'scan_id':scan['scan_id'],'confirmed':'1'})[0]==400
    assert before=={name:(root/name).read_bytes() for name in names}
    assert (folder/'S001.png').exists() and (folder/'S002.png').exists()


def test_scan_is_project_scoped_expires_and_requires_approval(web,tmp_path):
    item,folder=prepare(web,tmp_path)
    _,scan=post(web,item,'folder-scan',{'folder':str(folder)})
    other=start(web,scope='images')
    assert post(web,other,'folder-confirm',{'scan_id':scan['scan_id'],'confirmed':'1'})[0]==400
    assert post(web,other,'folder-scan',{'folder':str(folder)})[0]==400
    web[0].folder_imports.scans[scan['scan_id']]['created']-=1801
    assert post(web,item,'folder-confirm',{'scan_id':scan['scan_id'],'confirmed':'1'})[0]==400


def test_scan_rejects_relative_path_and_transparent_image(web,tmp_path):
    item,folder=prepare(web,tmp_path)
    assert post(web,item,'folder-scan',{'folder':'art'})[0]==400
    (folder/'S001.png').write_bytes(png('RGBA',color=(0,0,0,0)))
    _,scan=post(web,item,'folder-scan',{'folder':str(folder)})
    assert scan['ready']==0 and '透明' in scan['rows'][0]['error']


def test_partial_import_is_ordered_and_does_not_read_subfolders(web,tmp_path):
    item,folder=prepare(web,tmp_path)
    root=web[0].project(item['id']);plan=plan_fixture()
    second=copy.deepcopy(plan['shots'][0]);second['shot_id']='S002';plan['shots'].append(second)
    post(web,item,'plan-import',{'plan_text':json.dumps(plan)});action(web,item,'approve_storyboard')
    (folder/'S001.png').rename(folder/'s001_窗边.png')
    nested=folder/'nested';nested.mkdir();(nested/'S002.png').write_bytes(png())
    _,scan=post(web,item,'folder-scan',{'folder':str(folder)})
    assert scan['ready']==1 and scan['missing']==['S002'] and len(scan['rows'])==1
    status,result=post(web,item,'folder-confirm',{'scan_id':scan['scan_id'],'confirmed':'1'})
    assert status==200 and result['workflow']['ready_count']==1


def test_scan_limits_and_links(web,tmp_path,monkeypatch):
    item,folder=prepare(web,tmp_path)
    assert post(web,item,'folder-scan',{'folder':str(Path(folder.anchor))})[0]==400
    from avstudio import batch
    original=batch.has_link
    monkeypatch.setattr(batch,'has_link',lambda path: True if path==folder else original(path))
    assert post(web,item,'folder-scan',{'folder':str(folder)})[0]==400
    monkeypatch.setattr(batch,'has_link',original)
    for index in range(201):(folder/f'other{index}.png').write_bytes(b'x')
    assert post(web,item,'folder-scan',{'folder':str(folder)})[0]==400
