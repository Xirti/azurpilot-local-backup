# 本地构建

日常启动使用随包 Python、运行依赖、模型和前端产物，不执行在线安装。手动接入官方更新使用启动器「更多选项 → 版本更新」，完整流程见 [安装与更新](INSTALL_UPDATE.md)。

## 从源码构建

在独立目录准备 Windows x64 Python、uv 和 Node.js，执行：

```powershell
uv sync --frozen --no-dev --no-install-project
npm ci --prefix frontend --no-audit --no-fund
npm run build --prefix frontend
```

前端构建后生成 `.source-fingerprint`，并按维护清单固定源码标签、manifest 和 source.bundle。完整发布包还需要 `python-runtime`、`.venv`、模型，以及内嵌视频和字体的启动器；仅克隆源码不会自动得到这些运行材料。

## 离线恢复

已准备的完整包可直接打开根 EXE；移动目录时启动器会修正 Python 路径。重新构建环境需要提前准备匹配锁文件的 uv 缓存；重建前可用随包 uv 执行 `sync --frozen --offline --no-dev --no-install-project` 验证缓存是否齐全。前端依赖变化后，也需要提前准备对应锁文件的 npm 依赖。

`python-runtime/tools/uv.exe` 和基础 Python 位于 `.venv` 外，重建环境时使用这两个入口，避免删除正在执行的程序。不要为了整理包而按文件名删除运行库；SciPy 的 `_bws_test.py` 和 `_page_trend_test.py` 都是运行功能。

本地模式保留正常网络能力，游戏服务器检查、登录与校时按配置运行。更新由用户主动触发，平时启动不检查上游、不自动更新、不打开远程隧道。

公开包筛选见 [发布整理规则](RELEASE_EXPORT_RULES.md)；个人离线备份则在正常退出后复制整个安装文件夹。
