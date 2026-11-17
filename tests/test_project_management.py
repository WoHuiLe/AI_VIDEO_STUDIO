import json
import threading
from test_production import web, start, action, await_idle, upload, png
from test_web import request
from avstudio.storage import load_project, read_json


def manage(web,item,**fields):
    status,_,raw=request(web,f"/api/projects/{item['id']}/manage",fields)
    return status,json.loads(raw)


def test_rename_updates_name_without_changing_sources_or_shots(web):
    item=start(web,scope='images');root=web[0].project(item['id'])
    script=(root/'input/script_original.txt').read_bytes();plan=read_json(root/'planning/director.json')
    status,result=manage(web,item,operation='rename',title='新的作品名')
    assert status==200 and result['title']=='新的作品名' and load_project(root)['title']=='新的作品名'
    assert (root/'input/script_original.txt').read_bytes()==script and read_json(root/'planning/director.json')==plan
    assert manage(web,item,operation='rename',title=' ')[0]==400


def test_trash_is_confirmed_reversible_and_keeps_all_project_bytes(web):
    item=start(web,scope='images');action(web,item,'approve_storyboard');upload(web,item)
    root=web[0].project(item['id']);before={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
    assert manage(web,item,operation='trash')[0]==400
    status,result=manage(web,item,operation='trash',confirmed='1');assert status==200 and result['trashed']==item['id']
    assert not root.exists() and item['id'] not in [p['id'] for p in web[0].summaries()]
    trash=json.loads(request(web,'/api/trash')[2])['projects'];assert trash[0]['id']==item['id']
    archived=web[0].projects/'.trash'/item['id']/'project'
    assert before=={p.relative_to(archived).as_posix():p.read_bytes() for p in archived.rglob('*') if p.is_file()}
    assert manage(web,item,operation='restore')[0]==200
    assert before=={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
    assert json.loads(request(web,'/api/trash')[2])['projects']==[]
    assert manage(web,item,operation='trash',confirmed='1')[0]==200
    assert manage(web,item,operation='restore')[0]==200


def test_active_work_rejects_delete_and_rename_but_stop_preserves_project(web):
    entered=threading.Event()
    def planner(project,brief,feedback,work,cancelled,progress):
        entered.set();cancelled.wait(3)
        from avstudio.storage import StudioError
        raise StudioError('任务已取消')
    web[0].production.planner=planner
    from test_web import brief
    item=json.loads(request(web,'/api/projects',brief())[2]);root=web[0].project(item['id'])
    assert action(web,item,'plan')[0]==200 and entered.wait(2)
    assert manage(web,item,operation='trash',confirmed='1')[0]==400
    assert manage(web,item,operation='rename',title='不能改')[0]==400
    assert action(web,item,'cancel')[0]==200
    await_idle(web,item['id']);assert root.exists()
    assert manage(web,item,operation='trash',confirmed='1')[0]==200


def test_restore_never_overwrites_an_existing_project(web):
    item=start(web,scope='images');root=web[0].project(item['id'])
    assert manage(web,item,operation='trash',confirmed='1')[0]==200
    root.mkdir();marker=root/'keep.txt';marker.write_text('do not replace')
    assert manage(web,item,operation='restore')[0]==400 and marker.read_text()=='do not replace'


def test_invalid_management_requests_do_not_move_projects(web):
    item=start(web,scope='images');root=web[0].project(item['id'])
    for fields in [{'operation':'erase'},{'operation':'rename','title':'x'*201},{'operation':'restore'}]:
        assert manage(web,item,**fields)[0]==400
    assert root.is_dir()
