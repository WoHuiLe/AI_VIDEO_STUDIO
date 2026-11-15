# 本地工具使用指南

版本：0.1.0。工具可离线处理本地素材；图像生成需要在当次可用 AI 工具中执行，不绑定计费 API。

## 安装与启动

在工程目录使用 PowerShell：

```powershell
./environment/preflight.ps1
./environment/install.ps1 -Dev
./.venv/Scripts/python.exe -m avstudio --help
./.venv/Scripts/python.exe -m avstudio doctor
./.venv/Scripts/python.exe -m pytest -q
./environment/verify.ps1
```

当前电脑已经建立独立 `.venv`，复用系统已有 FFmpeg/FFprobe。安装脚本可重复执行，锁定版本见 `environment/requirements.lock.txt`。该锁包含测试与构建依赖，暂不拆分运行/开发两套锁；`-Dev` 仅声明本地可编辑安装的开发用途。脚本不安装系统软件、不改 PATH。迁移到其他 Python 版本或平台时应重新验证锁定依赖。

如果 FFmpeg 不在 PATH，可以为当前进程指定完整路径：`$env:AVSTUDIO_FFMPEG='C:\路径\ffmpeg.exe'`，FFprobe 对应 `AVSTUDIO_FFPROBE`。

卸载预览：`./environment/uninstall.ps1`；加 `-Execute` 仅删除本工程 `.venv`，不删除素材、代码或系统软件。本次没有执行卸载。

## 1. 从文案建立项目

```powershell
./.venv/Scripts/python.exe -m avstudio init projects/my-video --script 'C:\素材\文案.txt' --title '我的视频' --scope shots
./.venv/Scripts/python.exe -m avstudio plan projects/my-video
```

输入须为 UTF-8 文本。`init` 不覆盖非空项目，保存原文副本、哈希和段落编号。`plan` 创建 `planning/visual_task.md`，供当前 AI 或其他工具进行创意设计。它是任务书，不是自动生成的导演方案。

由执行者阅读文案，按 `docs/WORKFLOW.md` 完成情绪结构、分镜、美术设定和关键样张。建议把角色与美术说明保存为项目 `planning/character_bible.md` 和 `planning/style.md`，把实际提示/参考路径写入交接记录；打包时可选说明文件见下文。

## 2. 导入真实图片并创建镜头

```powershell
./.venv/Scripts/python.exe -m avstudio asset projects/my-video 'C:\素材\背景.png' --id BG01 --source '用户提供/工具生成' --usage-terms '填写来源和使用条件'
./.venv/Scripts/python.exe -m avstudio add-shot projects/my-video --id S001 --segments SEG001 --asset BG01 --duration 5 --description '窗边信封的特写，暖光落在纸面' --purpose '通过道具引入叙事'
./.venv/Scripts/python.exe -m avstudio check-assets projects/my-video
./.venv/Scripts/python.exe -m avstudio contact-sheet projects/my-video
```

导入文件保存为内容哈希路径。用同一 asset ID 导入新版会更新采用版本，旧文件保留；引用该素材的渲染缓存自动失效。尺寸按 EXIF 方向校正读取。构图裁切、人物脸手和角色一致性需审阅，工具仅提供尺寸风险和联系表。

`export-assets <项目>` 输出真实素材清单 `planning/assets.csv`；打包时也会自动生成。此 CSV 是清单导出，不是素材导入指令；素材变更使用 `asset`，提示与参考说明保存在 `planning/prompts.md`。

## 3. 编辑分镜与图层

`project.json` 是机器执行的主数据。`planning/storyboard.csv` 用于跨工具编辑文字分镜；`export-storyboard` 从主数据导出，`import-storyboard <项目> <CSV>` 导入已有镜头的编辑。CSV 未导入前不会改变渲染。CSV 不负责创建或修改图层运动，避免丢失参数。

可直接编辑 `project.json`，然后运行 `validate`。一个镜头示例：

```json
{
  "shot_id": "S001",
  "segment_ids": ["SEG001"],
  "source_text": "对应原文",
  "narrative_purpose": "建立空间和情绪",
  "visual_description": "窗边人物与信封，前景花枝",
  "duration_s": 5,
  "start_s": null,
  "end_s": null,
  "timeline_status": "provisional",
  "review_status": "approved",
  "layers": [
    {"asset_id": "BG01", "start": [0, 0, 1.04], "end": [-0.01, 0, 1.08]},
    {"asset_id": "FG01", "start": [0.02, 0, 1.12], "end": [-0.02, 0, 1.12]}
  ]
}
```

图层从背景到前景排序，所有源图使用相同画布。`start/end=[x,y,scale]`：x、y 为输出宽高的偏移比例，scale 为缩放。使用中心裁切和连续亚像素仿射采样，缓动为 smoothstep。scale 范围 1–4，偏移须满足 `abs(x),abs(y) <= (scale-1)/2`，防止画布露边。底层须完全不透明，遮挡区域需事先补绘；这不是自动深度估计或真实 3D。

已有蒙版时可提取透明图层：

```powershell
./.venv/Scripts/python.exe -m avstudio mask 'C:\素材\原图.png' 'C:\素材\灰度蒙版.png' 'C:\素材\人物图层.png'
```

蒙版与图像须同尺寸，白色保留、黑色透明。输出不覆盖现有文件。自动语义抠图和补背景需要图像工具或人工处理。

## 4. 渲染与交接

```powershell
./.venv/Scripts/python.exe -m avstudio validate projects/my-video
./.venv/Scripts/python.exe -m avstudio render projects/my-video --preview
./.venv/Scripts/python.exe -m avstudio render projects/my-video
./.venv/Scripts/python.exe -m avstudio package projects/my-video --renders
```

草稿可低清预览；正式渲染需把内容审核状态设为 approved。输出每镜头 MP4 和技术检查回执；尺寸、帧率、图层或素材变化后生成新文件，旧版保留。`--shot S001` 只处理指定镜头，未变化结果按哈希复用。每镜头时长取最近帧数，实际时长写入回执。

`package` 不加 `--renders` 可仅交付图片和策划。ZIP 保留项目主数据、原文、已登记素材、已有音频、分镜及指定策划文件，带逐文件 SHA256；解包后仍可用 `validate` 检查。额外策划文件固定支持 character_bible.md、style.md、review_notes.md 和 prompts.md，避免误打包任意目录的隐私文件。

## 5. 可选旁白、时间轴和粗剪

```powershell
./.venv/Scripts/python.exe -m avstudio audio projects/my-video 'C:\素材\我的录音.wav'
./.venv/Scripts/python.exe -m avstudio timeline projects/my-video 'C:\素材\timings.json' --confirmed
./.venv/Scripts/python.exe -m avstudio render projects/my-video
./.venv/Scripts/python.exe -m avstudio assemble projects/my-video
```

`timings.json` 格式：

```json
[
  {"shot_id": "S001", "start_s": 0, "end_s": 5, "sync_anchor": "经过实际旁白复核的短语"},
  {"shot_id": "S002", "start_s": 5, "end_s": 10, "sync_anchor": "下一个叙事节点"}
]
```

`--confirmed` 声明执行者已经对照实际录音复核；程序不会凭这个参数完成听音。换一份录音会使旧校准变为 provisional。首版粗剪只支持按分镜顺序连续直切，不支持空隙、重叠和自动转场；含旁白时所有镜头须对齐，镜头不足以覆盖旁白会拒绝截断。

`assemble --preview` 使用预览镜头。无旁白允许生成无声画面粗剪。`srt <项目>` 可按已对齐镜头导出独立字幕草稿，但镜头文本不一定等于真实发音或合理字幕分段，必须复核；没有自动 ASR 或逐词对齐功能，不默认执行字幕导出。

## 6. 技术检查与日志

`inspect <媒体文件> --output <报告.json>` 执行 FFprobe 和完整解码。`--probe-only` 跳过解码并记录 NOT_RUN。无字幕流不证明图片无文字；完整解码也不证明美术和语义正确。

项目 `work/events.jsonl` 记录重要操作；`planning/handoff.md` 记录用户认可、视觉检查、听音及下一步。每次修改说明影响的编号。源图、分层和独立镜头始终优先保留，以便在剪映继续。

## 7. 不消耗生成额度的技术演示

```powershell
./.venv/Scripts/python.exe -m avstudio demo projects/new-technical-demo
./.venv/Scripts/python.exe -m avstudio render projects/new-technical-demo
./.venv/Scripts/python.exe -m avstudio assemble projects/new-technical-demo
./.venv/Scripts/python.exe -m avstudio package projects/new-technical-demo --renders
```

演示只使用程序绘制的几何测试素材，不能作为绘本美术效果样片。正式画面验证需另选短文，进行实际创作与用户审阅。

## 技术资料

实现时核对了 [Pillow 图像模块文档](https://pillow.readthedocs.io/en/stable/reference/Image.html) 和 [FFmpeg 官方文档](https://ffmpeg.org/ffmpeg.html)。实际安装版本及检查结果以本机报告为准。
