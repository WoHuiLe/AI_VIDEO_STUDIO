import json
import shutil
import subprocess
import threading
from pathlib import Path
import pytest
from test_production import web, start, action, await_idle, upload, fixture_planner
from test_web import request, brief


def test_planning_records_real_phases_and_no_fake_percent(web):
    item=start(web,scope='images')
    job=item['workflow']['jobs'][0]
    assert job['status']=='succeeded' and job['stage']=='done'
    stages=[event.get('stage') for event in job['events']]
    assert stages[0]=='queued' and 'planning' in stages and 'validating' in stages
    assert all('percent' not in event for event in job['events'])


def test_render_reports_completed_shots_then_packaging(web):
    item=start(web,scope='shots');action(web,item,'approve_storyboard');upload(web,item);action(web,item,'approve_artwork')
    assert action(web,item,'deliver')[0]==200
    item=await_idle(web,item['id']);events=item['workflow']['jobs'][0]['events']
    counts=[(e['completed'],e['total']) for e in events if e.get('stage')=='rendering']
    assert counts==[(0,1),(1,1)]
    assert any(e.get('stage')=='packaging' for e in events)
    assert events[-1]['stage']=='done'


def test_active_planning_state_available_before_return_and_cancel_retains_status(web):
    entered=threading.Event()
    def waiting(project,brief,feedback,work,cancelled,progress):
        entered.set();cancelled.wait(3)
        progress('模型停止前的最后一次更新')
        raise __import__('avstudio.storage',fromlist=['StudioError']).StudioError('任务已取消')
    web[0].production.planner=waiting
    item=json.loads(request(web,'/api/projects',brief())[2])
    result=action(web,item,'plan')[1];assert entered.wait(2)
    running=web[0].detail(item['id'])['workflow']['jobs'][0]
    assert running['stage']=='planning' and running['status']=='running'
    assert '百分比' in running['message']
    assert action(web,item,'cancel')[0]==200
    final=await_idle(web,item['id'])['workflow']['jobs'][0]
    assert final['status']=='cancelled' and final['events'][-1]['stage']=='cancelled'


def test_activity_presenter_routes_confirmation_and_external_wait_truthfully():
    node=shutil.which('node')
    if not node:pytest.skip('node unavailable')
    source=Path('src/avstudio/web/static/activity.js').resolve()
    script=r'''
const assert=require('node:assert/strict');
const {activitySummary}=require(process.argv[1]);
let p={id:'p',status:'review',brief:{scope:'shots'},workflow:{shots:[{foregrounds:[]}],jobs:[],approvals:{},ready_count:0,has_plan:true}};
let s=activitySummary(p);assert.equal(s.title,'分镜方案待你确认');assert.equal(s.cta,'workflow');assert.match(s.label,/确认/);
p.workflow.approvals.storyboard='hash';s=activitySummary(p);assert.equal(s.title,'等待画面素材');assert.match(s.message,/没有 AI 生图任务/);
p.workflow.ready_count=1;s=activitySummary(p);assert.match(s.title,/画面.*确认/);
p.active_job='j';p.workflow.jobs=[{id:'j',action:'plan',status:'running',message:'模型正在生成'}];s=activitySummary(p);assert.equal(s.kind,'running');assert.match(s.title,/分镜/);assert.match(s.next,/无法计算准确百分比/);
p.workflow.jobs[0].status='cancelling';assert.equal(activitySummary(p).title,'正在停止任务');
p.active_job=null;p.workflow.error='网络不可用';assert.equal(activitySummary(p).kind,'failed');
p.workflow.error=null;p.workflow.approvals.artwork='hash';p.status='complete';assert.equal(activitySummary(p).cta,'outputs');
p.brief.scope='layers';assert.match(activitySummary(p).title,/分层/);
assert.equal(activitySummary(null).cta,'new');
'''
    result=subprocess.run([node,'-e',script,str(source)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_status_assets_are_served_on_workspace(web):
    status,_,html=request(web,'/')
    assert status==200 and 'activity-panel' in html.decode() and 'activity-open' in html.decode()
    assert request(web,'/activity.js')[0]==200


def test_atomic_write_waits_for_short_windows_reader_lock(tmp_path):
    import os,time
    if os.name!='nt':pytest.skip('Windows sharing-lock regression')
    from avstudio.storage import atomic_text
    path=tmp_path/'manifest.json';path.write_text('old')
    entered=threading.Event()
    def reader():
        with path.open('r'):
            entered.set();time.sleep(.08)
    thread=threading.Thread(target=reader);thread.start();assert entered.wait(1)
    try:atomic_text(path,'new')
    finally:thread.join()
    assert path.read_text()=='new'


def test_manifest_read_waits_for_windows_exclusive_access(tmp_path):
    import os,time
    if os.name!='nt':pytest.skip('Windows mandatory file lock')
    import msvcrt
    from avstudio.storage import read_text_file,sha256
    path=tmp_path/'storyboard.csv';path.write_text('content')
    entered=threading.Event()
    def locker():
        with path.open('r+b') as stream:
            msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,7)
            entered.set();time.sleep(.08)
            stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,7)
    thread=threading.Thread(target=locker);thread.start();assert entered.wait(1)
    try:assert read_text_file(path)=='content'
    finally:thread.join()
    assert len(sha256(path))==64
