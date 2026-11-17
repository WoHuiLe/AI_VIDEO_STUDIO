/* Task presentation is derived from persisted work, never simulated progress. */
function activitySummary(data) {
  if (!data) return {kind:'idle', title:'准备开始', message:'新建作品，或打开已有作品继续制作。', next:'尚未启动 AI 任务', cta:'new', label:'新建作品'};
  const flow=data.workflow, list=flow.shots||[], jobs=flow.jobs||[];
  const job=jobs.find(item=>item.id===data.active_job);
  if(data.active_job) {
    const stage=job?.stage || (job?.status==='queued'?'queued':job?.action==='plan'?'planning':'running');
    const labels={queued:'等待本机执行',planning:'AI 正在设计分镜',validating:'正在校验并保存分镜',rendering:'正在渲染动画镜头',assembling:'正在合成整段动画',packaging:'正在整理交付包',running:'任务正在执行'};
    return {kind:'running',title:job?.status==='cancelling'?'正在停止任务':labels[stage]||'任务正在执行',
      message:job?.message||'任务已提交，正在等待执行器状态。',
      next:job?.status==='cancelling'?'等待当前步骤安全停止，已有素材会保留':stage==='planning'?'模型生成无法计算准确百分比；返回后将校验方案，等待你确认':stage==='queued'?'本机按顺序处理任务，前一个任务完成后开始':'进度以真实处理结果更新；可切换面板查看其他内容',
      cta:'history',label:'查看执行记录',job};
  }
  if((flow.error||data.status==='error')&&jobs[0]?.status==='cancelled')return {kind:'waiting',title:'制作已停止',message:'已停止当前任务，已有文案、素材和成片都已保留。',next:'需要继续时，可在制作面板重新启动任务',cta:'workflow',label:'查看并继续制作'};
  if(flow.error||data.status==='error') return {kind:'failed',title:'任务需要处理',message:flow.error||'上次任务未完成，请查看执行记录。',next:'检查原因后可在制作面板重新开始',cta:'workflow',label:'查看并处理'};
  if(flow.needs_revision) return {kind:'waiting',title:'等待重新设计分镜',message:'修改意见已保存，当前方案尚未更新。',next:'选择本机 Codex 重新设计，或导入其他 AI 的新版方案',cta:'workflow',label:'查看修改与重新设计'};
  if(!flow.has_plan) return {kind:'waiting',title:'等待开始分镜设计',message:'文案已保存，AI 任务尚未启动。',next:'选择本机 Codex，或复制任务交给其他 AI',cta:'workflow',label:'开始设计 / 导入方案'};
  if(!flow.approvals.storyboard) return {kind:'waiting',title:'分镜方案待你确认',message:`已设计 ${list.length} 个镜头，目前等待确认分镜方向，还未进入配图。`,next:'查看方案后，点击“分镜通过，进入配图”',cta:'workflow',label:'查看分镜并确认 →'};
  if(flow.ready_count<list.length) return {kind:'waiting',title:'等待画面素材',message:`已准备 ${flow.ready_count} / ${list.length} 个镜头；当前没有 AI 生图任务在运行。`,next:'在所选图像工具生成后批量导入，或为合适镜头设置程序场景',cta:'workflow',label:'准备 / 导入画面 →'};
  if(data.brief.scope==='layers'&&!list.some(shot=>shot.foregrounds?.length)) return {kind:'waiting',title:'等待补充分层素材',message:'完整画面已齐，分层交付还需要至少一组真实透明前景。',next:'补充同画布前景，或在导出中选择其他交付范围',cta:'workflow',label:'查看分层要求'};
  if(!flow.approvals.artwork) return {kind:'waiting',title:'画面与动画待你确认',message:`${list.length} 个镜头已有画面，请检查预览是否符合预期。`,next:'在制作面板点击“确认画面与图层”，再生成正式交付',cta:'workflow',label:'查看画面并确认 →'};
  if(data.status==='complete') return {kind:'succeeded',title:'交付已完成',message:'视频与交付文件已生成，可以查看和下载。',next:'修改镜头后，需要重新确认画面并导出',cta:'outputs',label:'查看 / 下载交付 →'};
  return {kind:'waiting',title:'画面已确认，等待导出',message:'当前画面已通过确认，尚未生成本版正式交付。',next:'选择交付范围并启动导出',cta:'outputs',label:'进入导出 →'};
}
if(typeof module!=='undefined') module.exports={activitySummary};
