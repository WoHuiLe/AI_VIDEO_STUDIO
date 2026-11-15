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
    box.append(el('h3','资料已收到，下一步是设计分镜'),el('p','开始后会使用本机已登录 Codex 的额度。完成后先审核方案，再准备图片。','workflow-hint'),workflowButton('开始设计分镜','plan',project));
  } else if(!flow.approvals.storyboard) {
    box.append(el('h3',flow.needs_revision?'修改意见已保存，请重新设计分镜':'请先确认分镜方向'),el('p',`已设计 ${flow.shots.length} 个镜头。查看下方方案与逐镜头提示，认可后继续。`,'workflow-hint'));
    const approve=workflowButton('分镜通过，进入配图','approve_storyboard',project);approve.disabled=Boolean(flow.needs_revision);box.append(approve,workflowButton('重新设计分镜','plan',project,true));
  } else {
    box.append(el('h3',project.status==='complete'?'交付已生成，可在下方下载':'准备镜头素材'),el('p',`已准备 ${flow.ready_count} / ${flow.shots.length} 个镜头。可在 ChatGPT 等工具中按提示生图，再上传到对应镜头；本页不调用付费图像 API。`,'workflow-hint'));
    const row=el('div',undefined,'workflow-actions');
    if(!flow.approvals.artwork) { const approve=workflowButton('确认画面与图层','approve_artwork',project); approve.disabled=flow.ready_count!==flow.shots.length; const preview=workflowButton('生成动态预览','preview',project,true); preview.disabled=flow.ready_count!==flow.shots.length; row.append(approve,preview); }
    else row.append(workflowButton(project.status==='complete'?'重新检查并导出':'生成交付包','deliver',project));
    box.append(row);
    if(project.brief.scope==='layers') box.append(el('p','分层交付至少要有一组同画布背景和真实透明前景；单张完整图不能代替分层。','workflow-hint'));
  }
  const importer=el('details',undefined,'workflow-import'); importer.append(el('summary','使用其他 AI 的分镜 / 导入方案'));
  importer.dataset.stateKey='import-plan';
  if(flow.approvals.storyboard) importer.append(workflowButton('重新设计（保留原素材，重置绑定）','plan',project,true));
  const schema=el('a','下载分镜格式说明'); schema.href='/api/plan-schema'; schema.download='storyboard-schema.json'; importer.append(schema);
  const input=el('input'); input.type='file'; input.accept='.json'; input.setAttribute('aria-label','导入分镜 JSON');
  input.addEventListener('change',async()=>{ if(!input.files[0]) return; try{const form=new FormData();form.append('plan',input.files[0]);const result=await api(`/api/projects/${encodeURIComponent(project.id)}/plan-import`,{method:'POST',body:form});renderDetail(result);await loadProjects();}catch(error){toast(error.message);}finally{input.value='';} }); importer.append(input); box.append(importer);
  if(!flow.shots.length) return box;
  const list=el('div',undefined,'shot-list');
  for(const shot of flow.shots) {
    const card=el('details',undefined,'shot-card'); card.dataset.stateKey=`shot-${shot.shot_id}`;card.append(el('summary',`${shot.shot_id} · ${shot.background?'已配图':'待配图'} · ${shot.narrative_purpose}`),el('p',shot.visual_description),el('p',`景别：${shot.shot_size}；分层：${shot.layer_plan}`,'workflow-hint'));
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
