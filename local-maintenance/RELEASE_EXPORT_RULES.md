# 当前版本的离线发布整理规则

先解析安装根 `.updates/current.json`，从当前版本导出运行文件，目标使用一个全新的空目录。源码版本以当前 manifest 的标签为准，不能根据外层 r16 目录名猜测版本。

保留应用源码、前端源码和 dist、识别资源及模型、许可证、根 EXE、local-launcher、local-maintenance、local-repairs、.venv、python-runtime，以及 offline-artifacts 中的 source.bundle 和 release-runtime.json。EXE 视频已经内嵌，不另放 MP4。

公开包只保留 config 的模板与公共样式，不放用户实例、密码、数据库、日志、浏览器偏好或旧业务记录。新目录没有版本指针，直接使用导出的根版本；首次打开固定 EXE 自动初始化。

不复制 .git、.updates、versions、cache、log、frontend/node_modules、启动器 data/logs/settings.json、私人备份、开发缓存、测试与诊断材料。独立的用户完整备份不受公开包筛选限制，应保留其数据和版本目录。

运行依赖按目录和实际用途筛选，不能用 `*_test.py` 批量删除库文件。SciPy 的 `_bws_test.py`、`_page_trend_test.py` 是运行功能，必须保留。

正式包首页没有预置实例；初始化只准备部署设置和版本记录，不创建alas2或ap。公共template保留本地运行默认值，用户从首页创建或导入。发行时的source.bundle只保存当前干净源码及发行标签；日常更新仍可继承原源码历史。

导出后检查 source.bundle 与 manifest/标签一致，解释器路径可修复；在临时端口验证首次启动、网页/桌面交接及正常退出。检查游戏模块导入，运行包外的大世界计时与网络预检回归。不要为了验收运行用户账号任务。

当前用户只授权本地构建，不压缩、不上传。后续上传前，再按目标文件清单检查源码历史与包内容。
