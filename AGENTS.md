# AI Video Studio 协作约定

## 项目职责

将用户文案转化为有叙事设计的图片、分层和动态镜头，允许在任何约定阶段交接到剪映。优先阅读 README.md、docs/WORKFLOW.md 和当前项目的 planning/handoff.md。

## 制作

- 按 `.agents/skills/video-production/SKILL.md` 及制作规范执行；跨工具可直接阅读正文。
- 文案自动分段不是导演分镜。先理解语义、情绪和视觉表达，先做关键样张再批量生产。
- 没有真实旁白时不捏造同步时间；图片和独立镜头可以先交付。
- 不覆盖原始素材、既有音色或旧视频，不操作剪映和 VoiceStudio 私有数据库。
- 图像生成使用当次可用能力；无能力时生成明确任务包供用户或另一工具完成。不自动启用计费 API。
- 技术通过与创作认可分开。没有观看、听音或实际导入剪映就记录 NOT_RUN。

## 开发

- 使用工程 `.venv`，不改 VoiceStudio 环境、系统 PATH 或既有 MCP 配置。
- CLI：`.venv/Scripts/python.exe -m avstudio --help`。
- 测试：`.venv/Scripts/python.exe -m pytest -q`。
- 用程序测试素材检查代码，不自动返工正式视频。
- 工具参数通过列表调用，不拼 shell；项目引用须经路径边界检查。
- 代码、规范与模板纳入 Git，大型项目素材留本地；提交或推送范围按用户授权执行。
