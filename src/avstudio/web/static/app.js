const $ = (id) => document.getElementById(id);
const scopeNames = {images: "图片素材", layers: "分层素材", shots: "动态镜头", roughcut: "无字幕粗剪"};
const statusNames = {queued: "待处理", working: "处理中", review: "待你确认", complete: "已交付", feedback: "有新反馈", awaiting_assets: "待配图", error: "需要处理"};
const stageNames = {general: "整体 / 补充资料", storyboard: "分镜方案", artwork: "配图与美术", motion: "动态镜头", delivery: "最终交付"};
const decisionNames = {note: "补充说明", changes: "需要修改", approve: "已确认通过"};
const draftKey = "avstudio-brief-v1";
let token = "", selectedReferences = [], selectedNarration = null, activeProject = null;
let requestId = crypto.randomUUID().replaceAll("-", ""), feedbackRequestId = crypto.randomUUID().replaceAll("-", "");
let toastTimer;
let detailSignature = "";
const responseCache = new Map();
const detailOpenStates = new Map();

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function size(bytes) {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
function date(value) {
  return new Intl.DateTimeFormat("zh-CN", {timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false}).format(new Date(value));
}
function toast(message) {
  clearTimeout(toastTimer);
  $("toast").textContent = message; $("toast").hidden = false;
  toastTimer = setTimeout(() => { $("toast").hidden = true; }, 4000);
}
async function api(path, options = {}) {
  const cached = !options.method && path.startsWith('/api/projects') ? responseCache.get(path) : null;
  const headers = {"X-Studio-Token": token, ...options.headers};
  if (cached) headers['If-None-Match'] = cached.etag;
  const response = await fetch(path, {...options, headers});
  if (response.status === 304 && cached) return cached.data;
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "保存失败，请稍后重试");
  if (!options.method && response.headers.get('ETag')) responseCache.set(path,{etag:response.headers.get('ETag'),data:result});
  return result;
}
function fileURL(id, path, download = false) {
  return `/api/projects/${encodeURIComponent(id)}/file?path=${encodeURIComponent(path)}${download ? "&download=1" : ""}`;
}
function saveDraft() {
  $("character-count").textContent = `${$("script").value.length.toLocaleString()} 字`;
  try {
    const data = Object.fromEntries(new FormData($("project-form")));
    localStorage.setItem(draftKey, JSON.stringify({...data, request_id: requestId, start_now_checked: $('start-now').checked}));
    $("draft-state").textContent = "文字已在本机暂存";
  } catch { $("draft-state").textContent = "请保留页面，当前无法暂存"; }
}
function restoreDraft() {
  try {
    const data = JSON.parse(localStorage.getItem(draftKey) || "null");
    if (!data) return;
    for (const [name, value] of Object.entries(data)) {
      const input = $("project-form").elements.namedItem(name);
      if (input && typeof value === "string") input.value = value;
    }
    if (typeof data.request_id === "string" && /^[a-f0-9]{32}$/.test(data.request_id)) requestId = data.request_id;
    $("character-count").textContent = `${$("script").value.length.toLocaleString()} 字`;
    $("draft-state").textContent = "已恢复上次的文字草稿";
  } catch { /* A stale browser draft must never block new submissions. */ }
}
function refreshSelectedFiles() {
  const container = $("selected-files"); container.replaceChildren();
  const files = [...(selectedNarration ? [{file: selectedNarration, narration: true}] : []), ...selectedReferences.map(file => ({file, narration: false}))];
  for (const item of files) {
    const row = el("div", undefined, "file-chip");
    if (item.file.type.startsWith("image/")) {
      const image = el("img"); image.alt = "";
      const url = URL.createObjectURL(item.file); image.src = url;
      image.onload = () => URL.revokeObjectURL(url); image.onerror = () => URL.revokeObjectURL(url);
      row.append(image);
    }
    row.append(el("span", `${item.narration ? "配音 · " : ""}${item.file.name}`, "file-name"), el("small", size(item.file.size)));
    const remove = el("button", "×"); remove.type = "button"; remove.setAttribute("aria-label", `移除 ${item.file.name}`);
    remove.addEventListener("click", () => {
      if (item.narration) { selectedNarration = null; $("narration").value = ""; }
      else selectedReferences = selectedReferences.filter(f => f !== item.file);
      refreshSelectedFiles();
    });
    row.append(remove); container.append(row);
  }
}
function addReferences(files) {
  for (const file of files) {
    if (!selectedReferences.some(f => f.name === file.name && f.size === file.size && f.lastModified === file.lastModified)) selectedReferences.push(file);
  }
  refreshSelectedFiles();
}
function checkFiles(files) {
  if (files.length > 20) throw new Error("每次最多提交 20 个文件，请减少后重试。");
  if (files.reduce((n, f) => n + f.size, 0) > 100 * 1024 * 1024 - 1000000) throw new Error("文件合计接近或超过 100 MB，请减少或压缩后再提交。");
}
async function loadProjects() {
  const result = await api("/api/projects");
  const list = $("project-list"); list.replaceChildren();
  if (!result.projects.length) {
    const empty = el("div", undefined, "empty-state");
    empty.append(el("span", undefined, "empty-mark"), el("p", "这里还没有作品", "empty-copy"), el("small", "提交第一段文案，就从这里开始。"));
    list.append(empty); return;
  }
  for (const project of result.projects) {
    const card = el("button", undefined, "project-card"); card.type = "button";
    card.append(el("h3", project.title));
    const bottom = el("div", undefined, "card-bottom");
    bottom.append(el("span", `${scopeNames[project.brief.scope] || "素材"} · ${date(project.created_at)}`), el("span", statusNames[project.status] || "待处理", `badge ${project.status}`));
    card.append(bottom); card.addEventListener("click", () => openProject(project.id)); list.append(card);
  }
}
function section(title, content) {
  const box = el("section", undefined, "detail-section"); box.append(el("h3", title), content); return box;
}
function renderDetail(project) {
  if (activeProject && activeProject !== project.id) return;
  const signature = JSON.stringify(project);
  if (signature === detailSignature) return;
  detailSignature = signature;
  $("detail-title").textContent = project.title;
  const content = $("detail-content");
  const previousId = content.dataset.projectId;
  const opened = new Set(detailOpenStates.get(project.id) || []);
  if (previousId === project.id) {
    for(const detail of content.querySelectorAll('details[data-state-key]')) {
      if(detail.open) opened.add(detail.dataset.stateKey); else opened.delete(detail.dataset.stateKey);
    }
    detailOpenStates.set(project.id, opened);
  }
  const scrollTop = $('project-dialog').scrollTop;
  content.replaceChildren(); content.dataset.projectId = project.id;
  const meta = el("div", undefined, "detail-meta");
  meta.append(el("span", statusNames[project.status] || "待处理", `badge ${project.status}`), el("span", `${scopeNames[project.brief.scope]} · ${project.brief.ratio} · ${project.brief.style}`), el("span", date(project.created_at)));
  content.append(meta);
  content.append(buildWorkflow(project));
  const approveOption = $("feedback-decision").querySelector('option[value="approve"]');
  approveOption.disabled = true;
  if (approveOption.disabled && $("feedback-decision").value === "approve") $("feedback-decision").value = "note";
  $("feedback-form").querySelector('h3').textContent = project.workflow?.has_plan ? "补充资料与修改意见" : "补充资料（首次提交无需填写）";
  content.append(section("文案", el("div", project.script, "detail-text")));
  const requirements = [project.brief.notes, project.brief.must_keep && `必须保留：${project.brief.must_keep}`, project.brief.avoid && `避免出现：${project.brief.avoid}`].filter(Boolean).join("\n\n");
  if (requirements) content.append(section("制作要求", el("div", requirements, "detail-text")));
  if (project.files.length) {
    const links = el("div", undefined, "detail-files");
    for (const file of project.files) {
      const a = el("a", `${file.name} · ${size(file.bytes)}`); a.href = fileURL(project.id, file.path, true); links.append(a);
    }
    content.append(section("已收到的素材", links));
  }
  if (project.outputs.length) {
    const grid = el("div", undefined, "output-grid");
    for (const file of project.outputs) {
      const card = el("div", undefined, "output-card");
      if (/\.(png|jpe?g|webp)$/i.test(file.path)) { const image = el("img"); image.src = fileURL(project.id, file.path); image.alt = file.name; image.loading = "lazy"; card.append(image); }
      if (/\.mp4$/i.test(file.path)) { const video = el("video"); video.src = fileURL(project.id, file.path); video.controls = true; video.preload = "metadata"; card.append(video); }
      if (/\.(md|csv|srt)$/i.test(file.path) && file.bytes <= 1024 * 1024) {
        const details = el("details", undefined, "document-preview");
        details.dataset.stateKey = `document-${file.path}`;
        details.append(el("summary", "展开查看内容"));
        const text = el("pre", "正在读取……"); details.append(text);
        let loaded = false;
        details.addEventListener("toggle", async () => {
          if (!details.open || loaded) return;
          try { const response = await fetch(fileURL(project.id, file.path)); if (!response.ok) throw new Error("无法读取，请下载查看"); text.textContent = await response.text(); loaded = true; }
          catch (error) { text.textContent = error.message; }
        });
        card.append(details);
      }
      const link = el("a", `↓ ${file.name}`); link.href = fileURL(project.id, file.path, true); card.append(link); grid.append(card);
    }
    content.append(section("方案与制作产物", grid));
  }
  if (project.feedback.length) {
    const history = el("div");
    for (const item of [...project.feedback].reverse()) {
      const entry = el("div", undefined, "detail-feedback");
      entry.append(el("small", `${date(item.at)} · ${stageNames[item.stage] || item.stage} · ${decisionNames[item.decision] || item.decision}`), el("div", item.note || "这个部分通过，可按已确认方向继续。"));
      if (item.files.length) entry.append(el("small", `另附 ${item.files.length} 个文件`));
      history.append(entry);
    }
    content.append(section("你的反馈记录", history));
  }
  if (previousId === project.id) {
    for (const detail of content.querySelectorAll('details[data-state-key]')) if(opened.has(detail.dataset.stateKey)) detail.open=true;
    $('project-dialog').scrollTop = scrollTop;
  }
}
async function openProject(id) {
  try {
    const project = await api(`/api/projects/${encodeURIComponent(id)}`);
    activeProject = id; renderDetail(project);
    $("feedback-form").reset(); $("feedback-message").textContent = ""; $("feedback-files-label").textContent = "";
    feedbackRequestId = crypto.randomUUID().replaceAll("-", "");
    try { const draft = JSON.parse(localStorage.getItem(`avstudio-feedback-${id}`) || "null"); if (draft) { $("feedback-note").value = draft.note || ""; $("feedback-stage").value = draft.stage || "general"; $("feedback-decision").value = draft.decision || "note"; } } catch { /* optional draft */ }
    if ($('feedback-decision').value === 'approve') $('feedback-decision').value = 'note';
    if (!$("project-dialog").open) $("project-dialog").showModal();
  } catch (error) { toast(error.message); }
}
$("project-form").addEventListener("input", saveDraft);
$("project-form").addEventListener("change", saveDraft);
$("script-file").addEventListener("change", async (event) => {
  const file = event.target.files[0]; if (!file) return;
  if (file.size > 800000) { toast("文案文件过大，最多支持 20 万字。"); return; }
  try {
    const text = new TextDecoder("utf-8", {fatal: true}).decode(await file.arrayBuffer());
    if (text.length > 200000) throw new Error("文案最多支持 20 万字。");
    $("script").value = text.replace(/^\uFEFF/, ""); $("script-source").textContent = `已导入 ${file.name}`; saveDraft();
  } catch (error) { toast(error.message.includes("20 万") ? error.message : "请将文案保存为 UTF-8 TXT 或 Markdown 后导入。"); }
  event.target.value = "";
});
$("narration").addEventListener("change", event => { selectedNarration = event.target.files[0] || null; refreshSelectedFiles(); });
$("references").addEventListener("change", event => { addReferences(event.target.files); event.target.value = ""; });
const drop = $("reference-drop");
drop.addEventListener("dragover", event => { event.preventDefault(); drop.classList.add("dragover"); });
drop.addEventListener("dragleave", () => drop.classList.remove("dragover"));
drop.addEventListener("drop", event => { event.preventDefault(); drop.classList.remove("dragover"); addReferences(event.dataTransfer.files); });
window.addEventListener("dragover", event => { if (event.dataTransfer.types.includes("Files")) event.preventDefault(); });
window.addEventListener("drop", event => { if (event.dataTransfer.types.includes("Files")) event.preventDefault(); });
$("project-form").addEventListener("submit", async event => {
  event.preventDefault(); $("form-message").textContent = "";
  const button = $("submit-button"), oldText = button.textContent;
  try {
    if (!token) throw new Error("页面尚未连接本地服务，请刷新后重试。");
    checkFiles([...selectedReferences, ...(selectedNarration ? [selectedNarration] : [])]);
    const data = new FormData($("project-form")); data.set("request_id", requestId);
    if (selectedNarration) data.append("narration", selectedNarration);
    for (const file of selectedReferences) data.append("references", file);
    button.disabled = true; button.textContent = "正在保存文案与附件……";
    const project = await api("/api/projects", {method: "POST", body: data});
    $("project-form").reset(); selectedReferences = []; selectedNarration = null; refreshSelectedFiles();
    requestId = crypto.randomUUID().replaceAll("-", "");
    try { localStorage.removeItem(draftKey); } catch { /* optional */ }
    $("character-count").textContent = "0 字"; $("draft-state").textContent = "文字在本机自动暂存"; $("script-source").textContent = "先准备文字也可以，配音稍后补充。";
    $("form-message").className = "form-message success"; $("form-message").textContent = `「${project.title}」已保存，可在作品详情中查看制作进度。`;
    await loadProjects(); await openProject(project.id); toast("资料提交成功，已保存到本机工程。");
  } catch (error) { $("form-message").className = "form-message"; $("form-message").textContent = error.message; }
  finally { button.disabled = false; button.textContent = oldText; }
});
$("refresh-projects").addEventListener("click", () => loadProjects().catch(error => toast(error.message)));
$("close-dialog").addEventListener("click", () => $("project-dialog").close());
$("project-dialog").addEventListener("click", event => { if (event.target === $("project-dialog")) { const r = event.target.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) event.target.close(); } });
$("feedback-form").addEventListener("input", () => {
  if (!activeProject) return;
  try { localStorage.setItem(`avstudio-feedback-${activeProject}`, JSON.stringify({note: $("feedback-note").value, stage: $("feedback-stage").value, decision: $("feedback-decision").value})); } catch { /* optional */ }
});
function feedbackFileLabel() { const files = [...$("feedback-files").files, ...$("feedback-audio").files]; $("feedback-files-label").textContent = files.map(f => `${f.name}（${size(f.size)}）`).join("、"); }
$("feedback-files").addEventListener("change", feedbackFileLabel);
$("feedback-audio").addEventListener("change", feedbackFileLabel);
$("feedback-form").addEventListener("submit", async event => {
  event.preventDefault(); if (!activeProject) return;
  const button = $("feedback-button"); button.disabled = true; $("feedback-message").textContent = "";
  try {
    const files = [...$("feedback-files").files, ...$("feedback-audio").files]; checkFiles(files);
    const data = new FormData($("feedback-form")); data.set("request_id", feedbackRequestId);
    for (const file of $("feedback-files").files) data.append("supplements", file);
    if ($("feedback-audio").files[0]) data.append("narration", $("feedback-audio").files[0]);
    await api(`/api/projects/${encodeURIComponent(activeProject)}/feedback`, {method: "POST", body: data});
    try { localStorage.removeItem(`avstudio-feedback-${activeProject}`); } catch { /* optional */ }
    await openProject(activeProject); await loadProjects(); toast("反馈已保存，不需要再到聊天里重复提交。");
  } catch (error) { $("feedback-message").textContent = error.message; }
  finally { button.disabled = false; }
});
restoreDraft();
function updateSubmitLabel(){ $("submit-button").textContent = $("start-now").checked ? "提交并开始分镜" : "保存制作资料"; }
$("start-now").addEventListener('change',updateSubmitLabel);
api("/api/config").then(config => { token = config.csrf_token; let preference; try{preference=JSON.parse(localStorage.getItem(draftKey)||'null')?.start_now_checked;}catch{} $("start-now").checked = typeof preference === 'boolean' ? preference : false; updateSubmitLabel(); $("executor-message").textContent = config.executor?.available ? '使用本机已登录 Codex 的额度；也可取消勾选，仅保存资料。' : '可先保存资料，登录本机 Codex 后开始，或导入其他 AI 的分镜。'; return loadProjects(); }).catch(error => { $("form-message").textContent = `本地服务暂时无法连接：${error.message}`; $("project-list").replaceChildren(el("p", "无法读取作品，请刷新重试。", "empty-copy")); });
setInterval(() => {
  if (document.visibilityState !== "visible" || !token) return;
  loadProjects().catch(() => {});
  if ($("project-dialog").open && activeProject) {
    const requestedId = activeProject;
    api(`/api/projects/${encodeURIComponent(requestedId)}`).then(project => { if (activeProject === requestedId) renderDetail(project); }).catch(() => {});
  }
}, 5000);
