# AzurPilot 本机维护清单

此文供后续 AI 在更新或修复前读取。以现场的当前版本记录、manifest、provenance 和用户最新要求为准。

## 入口与本机

- 当前维护对象：`D:/pkz6666/Englishdownlad/Alas/AzurPilot_Release_Backup/local-2026-10-13-r16-release1/AzurPilot_Local`。外层目录名称仍是 r16，不能据此判断内部版本。
- 干净发行目录另置于`D:/pkz6666/Englishdownlad/Alas/AzurPilot_Release_Backup/local-2026-10-13-r23-release1/AzurPilot_Local`，不覆盖上面的现有安装及个人实例。发行目录无预置实例、浏览器偏好、日志和运行缓存。
- 固定入口为根目录 `AzurPilot-Local.exe`。`.updates/current.json` 指向当前版本；无记录时使用根目录。先解析该记录，再找实际源码、配置和日志。
- 日常旧副本 `D:/pkz6666/Englishdownlad/Alas/AzurPilot_Local` 与原安装 `D:/pkz6666/Englishdownlad/Alas/AzurPilot` 分开维护，不自动同步覆盖。
- 本机 i5-5200U，2 核 / 4 线程，约 8 GiB RAM；MuMu 12 分配 2 CPU / 4 GiB，1280×720。其余配置见 `machine-profile.json`，排查前复核现场。
- 官方更新源固定为 `https://github.com/wess09/AzurPilot.git`、`master`。私有源码备份仓库为 `Xirti/azurpilot-local-backup`。更新与上传是两个独立动作；当前不上传、不压缩。
- 用户要求：测试、mock、诊断脚本不进入源码提交、历史或发布包。个人配置、密钥、日志、浏览器数据不上传；测试在安装目录外进行。

## 一键更新结构

`managed_installation.py` 负责固定安装根、更新锁、原子版本切换和回退；`upstream_update.py` 调度更新；`updater_sources.py` 获取受控快照并三方合并；`updater_build.py` 准备依赖、构建与数据备份；`migrate_candidate.py` 调用上游配置和数据库迁移。

固定 EXE 的 `Program.InstallRoot` 不变，`Program.Root` 随当前版本切换。单实例锁、启动设置、WebView 用户数据和字体缓存跟随安装根；后台、配置、交接票据跟随当前版本。`ManagedEntry.cs` 的内部重启参数只等待原进程退出，再启动同一个固定 EXE。

更新顺序：核验旧版 → 正常停止旧服务 → 备份全部配置及业务数据 → 获取固定上游提交 → 三方合并 → 独立环境 → 前端构建 → 新提交、标签、manifest、source.bundle → 配置和业务数据迁移 → 服务验收 → 最后原子切换。失败不切换。回退恢复上一版及其数据，不把新版数据库反向覆盖旧版。

不要在当前运行目录执行官方安装器、reset --hard 或 clean。不要挪动旧标签绕过校验。遇到冲突按语义适配，不能整文件覆盖上游新增功能。`merge-adapters` 只接受三个输入哈希都匹配的已验证适配；输入改变即停止，不能放宽为无条件套用。

新旧环境与配置均为独立副本。Python 主版本要求、数据库结构或前端构建工具变化时，先验证当前引擎是否支持，再扩展；不把“更新流程成功”写成所有游戏任务已实测。

清理运行依赖时不能按 `*_test.py` 一刀切。SciPy 的 `stats/_bws_test.py` 与 `stats/_page_trend_test.py` 是运行时统计功能，游戏登录模块经 scipy.signal 会导入它们；先前误删曾导致 ModuleNotFoundError。包外测试目录仍排除，这两个库文件必须保留。更新验收包含游戏核心模块导入，不能只检查 WebUI。

## 配置边界

以下三项按用户要求保留，不做减负修改：

| WebUI 名称 | 键 | 原记录 |
| --- | --- | --- |
| 长时间等待时关闭模拟器 | `Alas.Optimization.CloseEmulatorDuringLongWait` | true |
| 当任务队列清空后 | `Alas.Optimization.WhenTaskQueueEmpty` | goto_main |
| 停止调度器后 | `Alas.Optimization.WhenSchedulerStopped` | stay_there |

迁移时保留用户的现场值。不要每次启动运行「恢复本地设置」；该操作会应用本地策略并暂停每月开荒等任务，只应由用户主动选择。暖启动仅修正环境路径，不重置配置或任务偏好。

本地部署保持：EnableReload=false、CheckUpdateInterval=0、AutoRestartTime=null、EnableRemoteAccess=false、WebuiHost=127.0.0.1、WebuiPort=22269、DiscordRichPresence=false、StartOcrServer=false、UseOcrServer=false、Run=null。启动控制台不自动恢复游戏任务。

减负方案保存在 `machine-profile.json` 与 `maintain.py`：OCR 使用 CPU/onnxruntime、关闭厂商 EP 自动安装，中文 alocr_cn_v3、英文 alocr_en_v2_6；普通/战斗截图间隔 0.3/1.0；遥测、Bug 上报和 LLM 分析关闭，大世界掉落截图 do_not。更新后按新版参数定义和中文选项名逐项核对，不用旧 JSON 整体替换新版模板。

nemu_ipc 和 MaaTouch 保留；持续超时才停止任务后单项比较 ADB。错误日志/截图保留用于诊断，不为了减负直接清空数据库。MuMu 内存和 CPU 不由维护工具擅自改变。

## 必须保留的修复与界面

1. 大世界 45 秒计时生命周期：新 daemon 开始和海域完成、奖励等出口清理旧计时；真实连续无法启动自律的保护仍有效。WebUI「自律寻敌时间限制（分钟）」属于另一层。
2. 无限等待入口仍核验固定版本、修复哈希、端口和前端错误；服务实际退出时立即报告。Git校验不再以20秒判断失败，改为最多120秒、每10秒报告状态、每200ms响应取消。服务正常初始化仍可等待，加载时能查看实时启动日志，失败时提供错误详情与保存日志。不能把所有失败都改为无限等待。
3. Windows 所有子命令显式 stdin=DEVNULL。控制线程持续读取 stdin 时，遗漏此项曾造成 Git 初始化 0 CPU 卡死；取消每 200ms 检查，只回收本次启动的子进程树。
4. 关闭服务核对 PID、创建时间、安装目录、父进程和随机事件。保留正常 ASGI/任务清理路径，不按进程名批量强杀。网页关闭接口只允许本机同源；桌面使用原窗口菜单与托盘。
5. 本地模式关闭页面自动外联和可选服务，保留游戏服务器检查、网关、NTP 等正常网络请求；旧 socket 全局拦截会阻塞任务，不得恢复。
6. 前端产物及 `.source-fingerprint` 配套发布；日常启动不执行 npm ci。保留默认新版界面及已有用户偏好，不反复清空 localStorage。
7. 桌面保留原界面与托盘。PerMonitorV2 DPI、可缩放边框、顶部抓边留白和至少 44px 顶栏配套保留；窄桌面窗口保留主页旁的悬停工具。最大化使用显示器工作区，保留 Windows 任务栏。
8. 启动器逻辑尺寸 800×450，中文小按钮，模式选择左右排列、下方返回，半透明磨砂面板和渐变交接。视频嵌入 EXE，独立媒体域按范围流式返回；正常首帧不闪中间 poster。字体嵌入 EXE，不依赖系统字体。
9. 新图标无文字，用于EXE、任务栏、托盘；小尺寸ICO突出圆形主体，窗口使用64px源、托盘按系统小图标尺寸选择。左上完整品牌图约116×93，距左22、距上17逻辑像素。重建EXE必须同时带视频和字体资源，并更新哈希与source.bundle。
10. LauncherDiagnostics.cs在服务启动前就可读取本次原生/后端进度、stderr、作业及GUI/WebUI日志，日志保存由用户选择本地路径。普通stderr警告只记录，不作为终止信号；读取完输出流后再判断最终状态，避免进程结束与UI回调的顺序竞争。诊断脚本/故障注入夹具仍只放包外。
11. 启动器明确进入首页，前端不能用last-path恢复覆盖该地址；托盘恢复仍按隐藏前地址。首次初始化只建部署设置与Git记录，不创建默认实例，不恢复/覆盖用户实例。没有实例也能启动、检查状态与备份；实例相关恢复在用户创建并选中实例后使用。
12. 新版、旧版的明暗使用colorMode的auto/light/dark，auto订阅系统外观并同步主题成员与自定义颜色；不要只改按钮而遗漏系统变化监听。公开template保留本地运行策略与三个原始等待选项，用户创建实例时复制模板。

## 验收与离线备份

针对更新验证：真实数据副本迁移与 SQLite quick_check、配置三项保留、健康接口/静态页面、前端与原生桌面交接、托盘和正常退出、失败和取消不切换、回退时数据对应。不得为验收启动用户游戏任务。

验证通过再固定新标签与 manifest；source.bundle 只包含允许发布的目标文件。`.updates`、`versions`、个人配置、WebView 数据、缓存与测试都不得混入源码。对外离线包应从当前版本导出干净运行文件，在新根目录使用固定 EXE；个人数据另备份。用户自己的完整离线备份可直接复制整个安装目录，包含当前/上一版和个人数据，不上传。

当前只构建与本地验证；上传、压缩和删除旧可运行版本均按用户后续要求执行。
