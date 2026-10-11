# 本机验收记录（2026-10-10）

此记录适用于 `AzurPilot_Local` 本轮生产源码与构建产物；完整机器与更新约束见 AI_LOCAL_MAINTENANCE.md。测试与临时检查脚本只留在本机，没有进入 GitHub 的任何提交历史。

| 项目 | 实际结果 |
| --- | --- |
| Python 运行环境 | CPython 3.14.6 / Windows x64；`uv sync --frozen --offline --no-dev` 从本机缓存安装142个运行依赖成功 |
| Windows 重建入口 | 基础 Python 与原生 uv 放在 `python-runtime/`，均在 `.venv` 之外；修正 uv 自删除文件占用后再次离线重建成功 |
| Python 针对性测试 | 39例通过：计时生命周期4、无限等待启动16、正常关闭12、维护/网络限制7 |
| 前端相关测试 | 3个模块共43例通过；主题默认值调整后重跑该模块23例，其余20例此前通过 |
| 生产构建 | 使用已准备的 node_modules，`npm --offline run build --prefix frontend` 成功；不代表新电脑能冷机离线安装 npm 依赖 |
| 源码恢复补丁 | 在临时上游夹具完成 apply --check、应用、reverse --check，并比对8个恢复文件，均通过 |
| 配置迁移夹具 | 三个大世界任务的 Enable=false / Sensitive=true 经当前 ConfigUpdater 迁移后保持；未借真实游戏任务触发迁移 |
| 生产指纹 | 测试和mock变化不改变指纹，生产源文件变化仍改变指纹；备份检出不依赖本机测试目录 |
| Git 克隆校验 | 对干净目标快照检出关键路径，127个修复/产物哈希及前端指纹匹配，HEAD匹配验收标签 |
| 实际 WebUI 启动 | 固定入口开启本地模式，在127.0.0.1:22269就绪；首次41.9秒，排除测试后的干净快照49.9秒；无固定总启动期限 |
| HTTP 资源 | /healthz 返回ok，/返回200；页面引用的8项资源以及两种本地字体、theme.css均返回200 |
| 后台身份 | Python解释器和工作目录均在本地版内，AZURPILOT_LOCAL_MODE=1，正常关闭通道存在；运行worker数为0 |
| 正常关闭 | 通过本目录关闭入口请求服务正常退出，后端及辅助后台关闭；没有按程序名称批量终止进程，保留MuMu和浏览器 |
| 网络限制 | 针对性检查验证标准socket对非回环DNS/连接的拒绝；允许本机服务。没有声称原生DLL被系统防火墙约束 |

本轮没有启动游戏，没有验证大世界实战稳定性、切海域识别精度或MuMu 3 GiB的效果。491条Nemu超时警告是旧日志事实；本地版的策略不会自动证明截图问题已修复。下一步游戏验证按 QUICK_CHECK.md 单项进行。

GitHub保存运行源码、生产前端、模型、模板、补丁、维护文档和实际恢复入口。真实配置、数据库、密钥、日志、截图、缓存、.venv、python-runtime、node_modules与验证脚本另存本机。发布范围见 publish-targets.json；私人配置备份在安装目录同级的 `AzurPilot_Local_Private_Backup/`。
