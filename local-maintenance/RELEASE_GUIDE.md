# 本机 Release 与原启动器备份

源码仓库用于追踪和恢复代码；GitHub 自动生成的 Source code ZIP 不含 Python 运行环境。Windows 离线 ZIP 额外包含 CPython、运行依赖、Git、ADB、预构建前端、模型与本地入口，免去重新安装依赖。运行游戏仍须连接游戏服务器，MuMu 需另行安装。

## 使用离线 ZIP

1. 下载名称带 `Windows-x64-offline` 的附件，解压到一个新目录。保留原安装与本机私有配置备份。
2. 如需恢复本机实例，把对应日期私有备份里的 `config/` 复制到新目录；包本身不含账号配置、数据库、密钥或日志。
3. 运行“初始化离线包.cmd”：修正解压路径对应的 Python home，只对缺失配置生成公共默认值，再逐项应用本地策略并检查版本与文件。已有三个等待/队列/停止选项保留原值。此步骤不启动游戏，不联网下载依赖。
4. 运行“启动WebUI_无限等待.cmd”。关闭用“关闭WebUI.cmd”。未恢复配置时得到一个默认实例，需自行配置模拟器连接；首次默认暂停智能调度、每月开荒和侵蚀1。

移动解压目录后重新执行初始化入口。不要直接从压缩包内运行文件。离线包只包含已安装依赖，不保证没有缓存时能重建 `.venv`；升级后的新依赖需要在候选目录另行准备。

## 原来的 EXE

单独备份的 `alas-launcher-2.2.4-original.exe` 对应本机 `AzurPilot/alas-launcher.exe`，文件不作修改。SHA256：`1ffca36b44b94608d9dbc5bc152c5602cec3929f0f76c00468ac03c08a9bff91`。它是更新/安装入口，需要完整候选安装环境与网络，单个 EXE 不能替代本机离线包。

核对该启动器 2.2.4 的源码：默认 setup 调用 git_update，再 uv_sync_project；git_update 调用部署脚本的 GitManager.git_install。当前本机上游部署实现会 reset --hard；启动器还会将 InstallDependencies 写为 true。`--skip-update` 只跳过仓库更新，不能据此认定完全离线或绕过依赖同步。

偶尔跟随官方更新时：在独立候选安装目录使用原启动器，确认 Repository / Branch 为用户选择的官方来源。联网准备好后关闭启动器，按 AI_LOCAL_MAINTENANCE.md 迁移修复、本地设置与私人配置，重新构建并验收、创建新标签，最后切换到本地 CMD 日常入口。现用本地版的 Repository 是自己的私人 GitHub 备份，不能通过它自动获取官方更新。

源码、离线 ZIP 与启动器分别备份；Release 附件排除项目测试、排查脚本、私人配置和日志。Python 依赖中的测试文件也不打包。保留组件许可证与版本信息，原启动器来源见 [启动器项目](https://github.com/wess09/alas-launcher/tree/2.2.4)，Release 机制见 [GitHub说明](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)。
