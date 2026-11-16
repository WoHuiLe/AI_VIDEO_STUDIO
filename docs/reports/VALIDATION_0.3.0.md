# 0.3.0 验证记录 · 2026-11-16

- `.venv/Scripts/python.exe -X utf8 -m pytest -q --junitxml=docs/reports/tests.xml`：74 passed。新增 11 项，覆盖共享任务包、粘贴校验和修正、批量提示、扫描预览、确认后交付、编号重复/未知/前景排除、源文件变更、方案版本、项目隔离、过期、回滚、非递归与部分导入、链接及数量上限。
- `node --check`：app.js、workflow.js 通过。
- `pip check`：无损坏依赖。
- `pip wheel --no-deps --no-build-isolation .`：构建 0.3.0 成功，核对 wheel 中共同规则 Markdown 和网页脚本已包含。
- video-production Skill 的 quick_validate 通过；按 skill-creator 做窄范围共同规范引用更新。
- 隔离 workspace / 8766 网页操作：复制完整分镜任务并核对剪贴板；无效 JSON 显示修正任务；有效 JSON 采用后审核；整批配图复制核对编号；本机文件夹扫描显示缩略图和尺寸；确认后显示 1/1 已准备。测试只用合成图片和固定分镜，无生图或付费 API。
- 实际 workspace / 8765 已重启，打开现有 14 镜头项目确认新入口显示，分镜及既有审核保留；未生成或改写正式图片。浏览器未记录脚本错误。
- 技术回归不能代替最终美术审核；真实图像工具是否逐张生成及其质量，取决于用户使用的工具与人工审核。
