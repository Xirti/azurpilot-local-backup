# AzurPilot 本机备份版

本机环境：Windows10 / i5-5200U双核四线程 / 8GB / MuMu12。来源与GPL-3.0许可证保留；上游基线见 local-maintenance/provenance.json。

- [给AI读取的维护与恢复清单](local-maintenance/AI_LOCAL_MAINTENANCE.md)
- [最简现场检查](local-maintenance/QUICK_CHECK.md)
- [日志分析](local-maintenance/LOG_ANALYSIS.md)
- [断网构建与限制](local-maintenance/OFFLINE_BUILD.md)
- [Release离线包与原启动器使用](local-maintenance/RELEASE_GUIDE.md)
- [机器可读策略](local-maintenance/machine-profile.json)
- [原版说明](README_UPSTREAM.md)

现有本机入口：“启动WebUI_无限等待.cmd” / “关闭WebUI.cmd” / “备份本机配置.cmd” / “恢复本地设置.cmd” / “检查本地设置.cmd”。WebUI只监听127.0.0.1:22269；启动不自动运行游戏任务。首次已暂停智能调度、每月开荒与侵蚀1，恢复任务前复核配置。

此仓库备份源码、预构建前端和模型。真实配置只保存在本机；准备的 Windows Release 离线包另带运行环境与初始化入口，原启动器 EXE 单独备份。源码 ZIP 不包含运行环境。依赖/前端/游戏任务的实际验收结果见 local-maintenance/VALIDATION.md。

按用户要求，只推送运行与恢复所需文件；测试、mock、开发排查脚本、CI 和本轮临时检查工具均留在本机，且不进入备份提交历史。维护文档记录验证结果；仓库中的启动、关闭、配置备份/恢复和离线重建脚本属于实际使用入口。
