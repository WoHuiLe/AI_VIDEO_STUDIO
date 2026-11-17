/* Workflow buttons always invoke real backend operations. */
function workflowButton(text, action, project, secondary = false) {
  const button = el('button', text, secondary ? 'workflow-button secondary' : 'workflow-button'); button.type = 'button';
  button.addEventListener('click', async () => {
    button.disabled = true;
    try { const form = new FormData(); form.set('action', action); const result = await api(`/api/projects/${encodeURIComponent(project.id)}/actions`, {method:'POST', body:form}); renderDetail(result); await loadProjects(); }
    catch(error) { toast(error.message); } finally { button.disabled = false; }
  }); return button;
}
function workflowUpload(project, shot, role) {
  const label = el('label', role === 'background' ? '上传图片 / 干净背景' : '＋ 透明前景', 'workflow-upload');
  const input = el('input'); input.type='file'; input.accept='.png,.jpg,.jpeg,.webp'; input.setAttribute('aria-label', `${shot.shot_id} ${role === 'background' ? '背景图片' : '透明前景'}`);
  input.addEventListener('change', async () => {
    if(!input.files[0]) return; input.disabled=true;
    try { checkFiles([...input.files]); const form=new FormData(); form.set('shot_id',shot.shot_id); form.set('role',role); form.append('image',input.files[0]); const result=await api(`/api/projects/${encodeURIComponent(project.id)}/shot-assets`,{method:'POST',body:form}); renderDetail(result); await loadProjects(); toast(`${shot.shot_id} 素材已保存`); }
    catch(error) { toast(error.message); } finally { input.disabled=false; input.value=''; }
  }); label.append(input); return label;
}
function buildWorkflow(project) {
  const flow=project.workflow || {shots:[], jobs:[], approvals:{}, has_plan:false, stage:'storyboard'};
  const box=el('section',undefined,'workflow'), steps=el('div',undefined,'workflow-steps');
  ['01 分镜设计','02 配图与分层','03 渲染与交付'].forEach((text,index)=>steps.append(el('span',text,['storyboard','artwork','delivery'][index]===flow.stage?'current':''))); box.append(steps);
  const job=flow.jobs.find(j=>j.id===project.active_job) || flow.jobs[0];
  if(project.active_job) { box.append(el('p',job?.message || '任务已排队，等待本机执行','workflow-hint'),workflowButton('停止当前任务','cancel',project,true)); return box; }
  if(flow.error) box.append(el('p',flow.error,'workflow-error'));
  if(!flow.has_plan) {
    box.append(el('h3','资料已收到，下一步是设计分镜'),el('p','开始后会使用本机已登录 Codex 的额度。完成后先审核方案，再准备图片。','workflow-hint'),workflowButton('用本机 Codex 设计分镜','plan',project));
  } else if(!flow.approvals.storyboard) {
    box.append(el('h3',flow.needs_revision?'修改意见已保存，请重新设计分镜':'请先确认分镜方向'),el('p',`已设计 ${flow.shots.length} 个镜头。查看下方方案与逐镜头提示，认可后继续。`,'workflow-hint'));
    const overview=el('details',undefined,'plan-overview');overview.open=true;overview.append(el('summary','整体方案与美术方向'));
    for(const [label,value] of [['内容理解',flow.summary],['美术方向',flow.visual_style],['人物与连续性',flow.character_notes]])if(value)overview.append(el('h3',label),el('p',value,'workflow-hint'));
    box.append(overview);
    const approve=workflowButton('分镜通过，进入配图','approve_storyboard',project);approve.disabled=Boolean(flow.needs_revision);box.append(approve,workflowButton('用本机 Codex 重新设计','plan',project,true));
  } else {
    box.append(el('h3',project.status==='complete'?'交付已生成，可在下方下载':'准备镜头素材'),el('p',`已准备 ${flow.ready_count} / ${flow.shots.length} 个镜头。可在 ChatGPT 等工具中按提示生图，保存到文件夹后批量导入，也可逐镜头上传；本页不调用付费图像 API。`,'workflow-hint'));
    const row=el('div',undefined,'workflow-actions');
    if(!flow.approvals.artwork) { const approve=workflowButton('确认画面与图层','approve_artwork',project); approve.disabled=flow.ready_count!==flow.shots.length; const preview=workflowButton('生成动态预览','preview',project,true); preview.disabled=flow.ready_count!==flow.shots.length; row.append(approve,preview); }
    else row.append(workflowButton(project.status==='complete'?'重新检查并导出':'生成交付包','deliver',project));
    box.append(row);
    if(project.brief.scope==='layers') box.append(el('p','分层交付至少要有一组同画布背景和真实透明前景；单张完整图不能代替分层。','workflow-hint'));
  }
  box.append(buildPlanHandoff(project, flow));
  if(flow.approvals.storyboard && flow.shots.some(s=>!s.scene)) box.append(buildBatchArtwork(project));
  if(!flow.shots.length) return box;
  const list=el('div',undefined,'shot-list');
  for(const shot of flow.shots) {
    const card=el('details',undefined,'shot-card'); card.dataset.stateKey=`shot-${shot.shot_id}`;card.append(el('summary',`${shot.shot_id} · ${shot.scene?'程序场景':shot.background?'已配图':'待配图'} · ${shot.narrative_purpose}`),el('p',shot.visual_description),el('p',`景别：${shot.shot_size}；分层：${shot.layer_plan}`,'workflow-hint'));
    const prompt=el('textarea');prompt.readOnly=true;prompt.rows=4;prompt.value=shot.image_prompt;prompt.setAttribute('aria-label',`${shot.shot_id} 配图提示`);card.append(prompt);
    const copy=el('button','复制配图提示','workflow-button secondary');copy.type='button';copy.addEventListener('click',()=>navigator.clipboard.writeText(shot.image_prompt).then(()=>toast('提示已复制')).catch(()=>toast('请直接选择提示文本复制')));card.append(copy);
    if(shot.background){const image=el('img');image.src=fileURL(project.id,shot.background.path);image.alt=`${shot.shot_id} 图片`;image.loading='lazy';card.append(image);if(flow.target_size&&(shot.background.width<flow.target_size[0]||shot.background.height<flow.target_size[1]))card.append(el('p','这张源图小于目标分辨率，放大或推近后可能变糊，请检查画质。','workflow-hint'));}
    if(shot.foregrounds.length){const thumbs=el('div',undefined,'layer-thumbs');for(const layer of shot.foregrounds){const wrapper=el('div'),image=el('img');image.src=fileURL(project.id,layer.path);image.alt=`${shot.shot_id} 透明前景`;const remove=el('button','移除此图层','workflow-button secondary');remove.type='button';remove.addEventListener('click',async()=>{try{const form=new FormData();form.set('action','remove_foreground');form.set('shot_id',shot.shot_id);form.set('asset_id',layer.asset_id);const result=await api(`/api/projects/${encodeURIComponent(project.id)}/actions`,{method:'POST',body:form});renderDetail(result);}catch(error){toast(error.message);}});wrapper.append(image,remove);thumbs.append(wrapper);}card.append(thumbs);}
    if(flow.approvals.storyboard){const uploads=el('div',undefined,'workflow-actions');uploads.append(workflowUpload(project,shot,'background'),workflowUpload(project,shot,'foreground'));card.append(uploads);} list.append(card);
  } box.append(list);
  if(flow.has_audio && flow.ready_count===flow.shots.length) box.append(buildTimeline(project,flow));
  return box;
}
function buildTimeline(project,flow) {
  const timeline=el('details',undefined,'timeline-editor');timeline.append(el('summary','旁白时间轴（粗剪需要，可稍后填写）'));
  timeline.dataset.stateKey='timeline';
  const audio=el('audio');audio.controls=true;audio.src=fileURL(project.id,flow.audio_path);audio.preload='metadata';timeline.append(audio,el('p','听取真实旁白后填写每镜头的开始和结束秒数。不要按字数猜测时间。','workflow-hint'));
  const entries=[];
  for(const shot of flow.shots){const row=el('div',undefined,'timeline-row');row.append(el('span',shot.shot_id));const start=el('input'),end=el('input');for(const item of [start,end]){item.type='number';item.min='0';item.step='0.01';}start.placeholder='开始秒';end.placeholder='结束秒';start.setAttribute('aria-label',`${shot.shot_id} 开始秒`);end.setAttribute('aria-label',`${shot.shot_id} 结束秒`);if(shot.timing?.start_s!=null)start.value=shot.timing.start_s;if(shot.timing?.end_s!=null)end.value=shot.timing.end_s;row.append(start,end);timeline.append(row);entries.push({shot,start,end});}
  const confirm=el('label',undefined,'start-option'),checkbox=el('input');checkbox.type='checkbox';confirm.append(checkbox,document.createTextNode('我已对照真实旁白复核这些时间'));timeline.append(confirm);
  const save=el('button','保存旁白时间轴','workflow-button secondary');save.type='button';
  save.addEventListener('click',async()=>{try{if(!checkbox.checked)throw new Error('请先对照旁白复核并勾选确认');const times=entries.map(({shot,start,end})=>{if(start.value===''||end.value==='')throw new Error('请填完每个镜头的时间');return{shot_id:shot.shot_id,start_s:Number(start.value),end_s:Number(end.value)};});const form=new FormData();form.set('timings',JSON.stringify(times));form.set('confirmed','1');const result=await api(`/api/projects/${encodeURIComponent(project.id)}/timeline`,{method:'POST',body:form});renderDetail(result);toast('时间轴已保存');}catch(error){toast(error.message);}});timeline.append(save);return timeline;
}
// Portable handoff text and folder scans remain available during status polling.
const handoffDrafts = new Map();
function handoffState(project) {
  if(!handoffDrafts.has(project.id)) handoffDrafts.set(project.id, {plan:'',folder:'',scan:null,repair:''});
  return handoffDrafts.get(project.id);
}
function plainButton(text, handler, secondary=true) {
  const button=el('button',text,secondary?'workflow-button secondary':'workflow-button');button.type='button';
  button.addEventListener('click',async()=>{button.disabled=true;try{await handler();}catch(error){toast(error.message);}finally{button.disabled=false;}});return button;
}
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); toast('完整任务已复制'); }
  catch(error) { throw new Error('浏览器未允许复制，请下载任务文件或选择文本复制'); }
}
function taskControls(project,kind) {
  const row=el('div',undefined,'workflow-actions');
  const get=()=>api(`/api/projects/${encodeURIComponent(project.id)}/task-pack?kind=${kind}`);
  row.append(plainButton(kind==='images'?'一键复制全部配图任务':'复制完整分镜任务',async()=>copyText((await get()).text),false),
    plainButton('下载任务文件',async()=>{const task=await get(),url=URL.createObjectURL(new Blob([task.text],{type:'text/markdown;charset=utf-8'})),link=el('a');link.href=url;link.download=task.filename;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}));
  return row;
}
function buildPlanHandoff(project,flow) {
  const state=handoffState(project),box=el('details',undefined,'workflow-import handoff-panel');box.dataset.stateKey='import-plan';
  box.open=!flow.has_plan;
  box.append(el('summary','其他 AI 设计分镜 · 复制任务 / 粘贴结果'));
  if(flow.approvals.storyboard) box.append(workflowButton('改用本机 Codex 重新设计（重置绑定）','plan',project,true));
  box.append(el('p','与本机 Codex 共用制作规范 1.1（源自 video-production Skill）。完整任务含原文、要求、反馈、格式和示例；参考图片需另外交给 AI。先复制任务，再把返回的 JSON 粘贴到这里。','workflow-hint'),taskControls(project,'storyboard'));
  if(flow.has_plan)box.append(el('p','采用新版分镜会重置审核和图片绑定，原素材文件保留。','workflow-hint'));
  const text=el('textarea');text.rows=5;text.placeholder='粘贴其他 AI 返回的完整分镜 JSON，也支持 ```json 围栏';text.value=state.plan;text.setAttribute('aria-label','其他 AI 分镜结果');text.addEventListener('input',()=>state.plan=text.value);
  const input=el('input');input.type='file';input.accept='.json';input.setAttribute('aria-label','导入分镜 JSON');
  const resultBox=el('div');
  function showRepair(){resultBox.replaceChildren();if(state.repair){resultBox.append(el('p','校验未通过，当前分镜未改变。复制下面的修正任务给原 AI。','workflow-error'),plainButton('复制修正任务',()=>copyText(state.repair)));}}
  showRepair();
  const save=plainButton('校验并采用分镜',async()=>{
    if(!text.value.trim()&&!input.files[0])throw new Error('请粘贴结果或选择 JSON 文件');
    const form=new FormData();form.set('plan_text',text.value);if(input.files[0])form.append('plan',input.files[0]);
    const result=await api(`/api/projects/${encodeURIComponent(project.id)}/plan-import`,{method:'POST',body:form});
    if(result.valid===false){state.repair=result.repair_task;showRepair();toast(result.error);return;}
    state.plan='';state.repair='';state.scan=null;renderDetail(result);await loadProjects();toast('分镜已采用，请审核方向');
  },false);
  box.append(text,el('p','或上传一个 JSON 文件（粘贴与文件选一种）','workflow-hint'),input,save,resultBox);return box;
}
function buildBatchArtwork(project) {
  const state=handoffState(project),box=el('section',undefined,'handoff-panel batch-artwork');
  box.append(el('span','BATCH WORKSPACE','eyebrow'),el('h3','整批配图，统一导入'),
    el('p','① 复制全部任务 → 在 ChatGPT / 其他 AI 中按编号独立生图 → 保存为 S001.png 等文件。先做关键样张确认方向，再生成其余图片。','workflow-hint'),taskControls(project,'images'),
    el('p','② 填写保存图片的本机文件夹路径。扫描本层 PNG / JPG / WebP；不读取子文件夹。第一轮放完整图，透明前景之后按需补充。','workflow-hint'));
  const path=el('input');path.type='text';path.placeholder='例如 C:\\Users\\你的用户名\\Downloads\\我的配图';path.value=state.folder;path.setAttribute('aria-label','配图文件夹完整路径');path.addEventListener('input',()=>{state.folder=path.value;state.scan=null;preview.replaceChildren();});
  const preview=el('div');
  const draw=()=>{
    preview.replaceChildren();const scan=state.scan;if(!scan)return;
    preview.append(el('p',`可导入 ${scan.ready} 张；尚缺 ${scan.missing.length} 个镜头${scan.missing.length?'：'+scan.missing.join('、'):''}`,'workflow-hint'));
    const grid=el('div',undefined,'import-contact-sheet');
    scan.rows.forEach((row,index)=>{const card=el('figure',undefined,row.error?'import-tile issue':'import-tile');
      if(!row.error){const image=el('img');image.loading='lazy';image.alt=`${row.shot_id} 待导入图片`;image.src=`/api/projects/${encodeURIComponent(project.id)}/scan-thumbnail?scan_id=${encodeURIComponent(scan.scan_id)}&index=${index}`;card.append(image);}
      card.append(el('figcaption',`${row.shot_id||'未匹配'} · ${row.name}`),el('p',row.error||`${row.width} × ${row.height}`,'workflow-hint'));
      row.warnings.forEach(w=>card.append(el('p',w,'workflow-hint')));grid.append(card);});preview.append(grid);
    const confirm=plainButton(`确认导入已匹配的 ${scan.ready} 张图片`,async()=>{
      const form=new FormData();form.set('scan_id',scan.scan_id);form.set('confirmed','1');
      const result=await api(`/api/projects/${encodeURIComponent(project.id)}/folder-confirm`,{method:'POST',body:form});
      state.scan=null;renderDetail(result);await loadProjects();toast('图片已复制并绑定，源文件保留');
    },false);confirm.disabled=!scan.ready;preview.append(confirm,el('p','重复文件不自动选择。整理文件后重新扫描；可先导入部分镜头。确认会替换同编号的完整图绑定。','workflow-hint'));
  };
  const scan=plainButton('扫描文件夹并预览',async()=>{const form=new FormData();form.set('folder',path.value);state.scan=await api(`/api/projects/${encodeURIComponent(project.id)}/folder-scan`,{method:'POST',body:form});draw();});
  box.append(path,scan,preview);draw();return box;
}
