# 仓库维护约定

这是 AzurPilot Windows 本地版的源码备份。使用简体中文交流、注释和提交说明。

- 只提交运行源码、必要构建产物、识别资源、配置模板、许可证及维护工具。测试、mock、开发排查脚本、CI、私人实例、密钥、数据库、日志、缓存和独立运行环境不进入提交。
- 发布范围见 `local-maintenance/publish-targets.json`。完整可运行环境由 Release ZIP 提供；源码仓库不携带 `.venv`、`python-runtime` 或 `offline-artifacts`。
- 先读 `local-maintenance/AI_LOCAL_MAINTENANCE.md`，更新与安装见 `local-maintenance/INSTALL_UPDATE.md`，发行整理见 `local-maintenance/RELEASE_EXPORT_RULES.md`。
- 保留用户已有修改及配置；不要为了验收运行游戏账号任务。检查脚本和夹具放在仓库外，使用临时实例或模拟服务验证。
- 验证只运行与修改有关的检查，说明实际结果。不要按 `*_test.py` 删除依赖运行文件，SciPy 同名功能模块必须保留。
- 不强制推送、不覆盖已有标签。发行标签对应包内固定源码；源码备份提交可另有固定标签，`manifest.json` 应指向自身有效标签并保留正确文件哈希。
- 涉及配置定义时先修改 `module/config/argument/` 源定义，再运行生成器；涉及 API 契约时同步对应生成产物。游戏交互使用截图正向确认与现有 UI 导航，不用固定等待猜测页面状态。
