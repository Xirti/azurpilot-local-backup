# AzurPilot 本机维护入口：给后续 AI 读取

核查日期：2026-10-10。先读本文件、`machine-profile.json`、`LOG_ANALYSIS.md` 和 `OFFLINE_BUILD.md`，再核对实际版本。机器和任务状态会变，记录不能代替现场检查。

## 用户授权与当前目录

- 用户要求：自主检查日志、保留已验证修复、建立减负与更新后恢复清单；用户自己决定何时更新，建立私有 GitHub 备份；允许关闭远程访问。
- 推送范围：只提交运行与恢复所需文件。测试、mock、开发排查脚本与CI留在本机，禁止进入备份的任意提交历史；验证报告可以提交，验证脚本不提交。
- 原安装：`D:\pkz6666\Englishdownlad\Alas\AzurPilot`，端口 22267。此轮原安装只关闭 `EnableRemoteAccess`；没有启动游戏、改变 MuMu 参数或替换原启动入口。
- 独立本地版：`D:\pkz6666\Englishdownlad\Alas\AzurPilot_Local`，端口 22269。两者使用各自的源码和配置，禁止同时对同一游戏账号运行调度器。
- 私有源码备份：[Xirti/azurpilot-local-backup](https://github.com/Xirti/azurpilot-local-backup)。GPL-3.0，保留上游许可证、原 README 与来源说明。
- 上游基线：`ba2a5146dde4b6dbe72054a466ab149a408e6661`；本轮提交以 `refs/tags/local-2026-10-10-r2` 为准，上一版标签保留。以后使用新的验收标签，不能挪动旧标签绕过校验。

## 机器事实与减负边界

Intel i5-5200U，**2 个物理核心 / 4 个逻辑线程**，7.88 GiB RAM，Windows 10 Pro 19045。MuMu 12 实际 VM 分配 2 CPU / 4 GiB，1280×720，观察到低帧率配置 30 FPS。不要把“四线程”误写成“四核心”。核查时可用内存约 1.0–1.4 GiB，这是停机时的单次快照，不能证明任务期间的峰值或截图超时根因。

WebUI 页面依然会消耗浏览器内存。CMD 是启动入口，实际服务是 Python 后端加浏览器前端。Chrome/Edge 同时有较多进程，单进程占用不能归到 AzurPilot 页面。需要浏览器任务管理器按标签核对；运行任务不必常开网页。

本地版新浏览器默认“界面设置 → 主题 → 简约”，默认减弱动效；已有明确偏好保留。开发者工具的“减少动效模拟”影响当前浏览器。运行监控选“日志”而非“截图”可取消 preview 订阅；它不是 `alas2.json` 的截图方法开关。主题等存于 localStorage，按浏览器和网页来源区分；更换端口、浏览器或无痕窗口需要复核。

## 每次更新必须恢复的本地策略

先正常关闭 WebUI，再运行 `恢复本地设置.cmd`。此工具先在仓库同级保存真实 `config/`，只逐项修改现存键；新版缺少字段时停止，不用旧 JSON 整体覆盖新结构。默认同时暂停每月开荒、侵蚀1与智能调度，并将其“敏感任务”设为开启。恢复任务运行需由用户明确选择。

| 部署 / WebUI 选项 | 本地值 | 原因 |
| --- | --- | --- |
| 允许更新 / `EnableReload` | false | 禁止 WebUI 应用更新覆盖补丁 |
| 检查更新间隔 / `CheckUpdateInterval` | 0 | 生命周期仅在间隔 >0 时创建检查循环；false 的 EnableReload 不会单独停掉检查 |
| 定时更新 / `AutoRestartTime` | null | 取消定时更新计划 |
| 远程访问 / `EnableRemoteAccess` | false | 关闭 SSH 隧道与断线重连 |
| `WebuiHost` / `WebuiPort` | 127.0.0.1 / 22269 | 仅本机访问，与原安装端口区分 |
| `StartOcrServer` / `UseOcrServer` | false / false | 单实例保持内置 OCR，避免额外 OCR 服务 |
| `DiscordRichPresence` / `Run` | false / null | 关闭额外连接；启动 WebUI 不自动运行账号任务 |
| `Repository` / `Branch` | 私有备份仓库 / main | 原上游地址保存在 provenance，人工更新从候选目录进行 |
| `GitExecutable` | ./.venv/Scripts/git/cmd/git.exe | 本机与 Release 携带原安装的 Git 工具，不依赖系统 Git 绝对路径 |

| WebUI 选项名字 | JSON 键 | 本地策略 |
| --- | --- | --- |
| OCR设备 | `Alas.Optimization.OcrDevice` | `"cpu"` |
| 自动安装并使用厂商 EP | `Alas.Optimization.OcrWindowsMlVendorEp` | `false` |
| 放慢截图速度至 X 秒一张 | `Alas.Optimization.ScreenshotInterval` | `0.3` |
| 战斗中放慢截图速度至 X 秒一张 | `Alas.Optimization.CombatScreenshotInterval` | `1.0` |
| 遥测数据上报 | `Alas.DropRecord.TelemetryReport` | `false` |
| Bug 日志上报 | `Alas.DropRecord.BugReport` | `false` |
| 启用 LLM 错误分析 | `Alas.Error.LlmAnalysis` | `false` |
| 侵蚀一掉落截图 | `Alas.DropRecord.OpsiHazard1Leveling` | `"do_not"` |
| 短猫掉落截图 | `Alas.DropRecord.OpsiMeowfficerFarming` | `"do_not"` |
| 大世界每日掉落截图 | `Alas.DropRecord.OpsiDaily` | `"do_not"` |
| 隐秘海域掉落截图 | `Alas.DropRecord.OpsiObscure` | `"do_not"` |
| 深渊海域掉落截图 | `Alas.DropRecord.OpsiAbyssal` | `"do_not"` |
| 塞壬要塞掉落截图 | `Alas.DropRecord.OpsiStronghold` | `"do_not"` |
| 每月开荒掉落截图 | `Alas.DropRecord.OpsiExplore` | `"do_not"` |
| 其他大世界任务掉落截图 | `Alas.DropRecord.OpsiOther` | `"do_not"` |
| OCR后端 | `Alas.Optimization.OcrBackend` | `"onnxruntime"` |
| OCR中文模型版本 | `Alas.Optimization.OcrModelVersionChinese` | `"alocr_cn_v3"` |
| OCR英文模型版本 | `Alas.Optimization.OcrModelVersionEnglish` | `"alocr_en_v2_6"` |

OCR 旧模型显式固定是为了避免未来 `auto` 改指更大模型。此轮选择与原 CPU/auto 实际使用的旧模型一致，不代表 lite 模型已经通过游戏精度验收。不要默认切 GPU 或 pro；只有现有截图证明识别不足时再单项比较。

## 保持或有条件试验的设置

| WebUI 选项 | 本机现状 / 建议 | 使用条件与验证 |
| --- | --- | --- |
| 模拟器设置 → 选择截图方案 | 现为 nemu_ipc | 高速但仍频繁超时；连续重试耗尽时先检查 VM 已开且 ADB 在线，再单项试 ADB 截图。停止任务后更改，不同时切控制方案 |
| 模拟器设置 → 选择控制方案 | 现为 MaaTouch | 保留；单次失败随后恢复不能断言永久失效。重复初始化失败才试 ADB 控制；旧 minitouch 已有空数据报错，不能盲目改回 |
| 放慢截图速度至 X 秒一张 / 战斗中放慢截图速度至 X 秒一张 | 0.3 / 1.0 | 当前已达帮助文案上限，不直接建议 0.8 或 2.0 等越界值 |
| 囤积任务 X 分钟 | 现为 1 | 可试 3–5，减少零散唤醒；先确认紧迫委托、演习和活动时限，不能直接写成必改 |
| 长时间等待时关闭模拟器 | 原配置已开启 | 用户要求保持原状，不纳入减负修改；当前逻辑等待 >3 小时才关闭 |
| 当任务队列清空后 | 原配置 goto_main（返回主界面） | 用户要求保持原状，不改为 close_game；恢复工具保留用户当前选择 |
| 停止调度器后 | 原配置 stay_there（停留当前页面） | 用户要求保持原状，不改为关闭游戏或模拟器；与关闭 WebUI 是不同触发路径 |
| 在任务开始前预热启动模拟器与游戏 / 预热分钟数 | 已开启 / 15 | 冷启动可靠性与空闲占用存在取舍；先保留，若启动稳定后再试关闭或缩短 |
| 敏感任务出错时禁止重启 | 已开启 / StrictRestart=true | 仍需每个任务的“敏感任务”开启才保护开荒；并非一项全局开关就自动覆盖所有任务 |
| 同一任务连续重启上限 | 现为 3 | 不再增加重试次数掩盖设备/地图问题；核对该版本实际累计与复位规则 |
| 出错时，保存 Log 和截图 / 错误日志过期天数 / 出错时，保留最后 X 张截图 | true / 7 / 10 | 保留诊断依据；不要为省磁盘关掉所有错误记录 |
| 截图保留天数 | 现为 0 | 日志与截图累积有磁盘风险；可在确认需要留存的统计后选 7–14 天，不自动删除数据库 |
| MuMu 分配内存 | 实际 4 GiB | 可单项 A/B 试 3 GiB，观察一次普通任务与海域切换；内存不足或加载变慢就恢复 4 GiB。没有证据支持强制 4 CPU |

表中数值和枚举必须按更新后的 `module/config/argument/args.json` 与 zh-CN 翻译再核对。带有“可试”的建议不由恢复工具自动执行。

## 必须保留的代码与验收

1. 45 秒计时生命周期：`module/os/map.py` 进入新 daemon 清理旧计时；`module/os_handler/map_event.py` 在海域完成 / 奖励等三条出口清理。真实连续无法启动自律的 46 秒保护仍触发。WebUI 的“自律寻敌时间限制（分钟）”属于另一层，调大它不能修复此问题。
2. 无限等待：`local-repairs/webui_launcher.py` 没有总启动期限，仍会检查后端退出、错误端口和前端失败；它不是所有异常都无期限等待。校验固定提交、修复哈希、更新关闭设置；缺依赖不会自动删除 `.venv` 重装。
3. 正常关闭：`module/runtime/local_webui_stop.py` + gui 的服务退出事件；`webui_stop.py` 核对 PID、创建时间、目录、父进程与随机事件，正常关闭 ASGI 和任务辅助进程。重复关闭无害；不按 python.exe/ssh.exe 名字批量杀进程。
4. 本地模式：前端 Clarity 脚本已移除，CSP 限制页面自动外联；Python 启动时加载 `offline-runtime/sitecustomize.py`，阻止标准 socket 的外部 DNS/连接，允许回环 WebUI/ADB。它不是 OS 防火墙，不能约束原生 DLL 或用户手动打开的外链。游戏服务器仍需网络。
5. `deploy/frontend.py` 在本地模式缺产物 / 指纹不符时直接报告原因，不执行 npm ci。预构建前端随私有源码备份，生产启动不依赖 Node。

新版合入同类上游修复时先做语义比较；不要重复补丁，也不要删除真实故障保护。哈希只用来发现文件变化，不能证明新版本正确。验收后再写新 manifest 和新标签。

## 用户决定更新的完整流程

用户已明确：上述三个等待/队列/停止选项不用于减负。原安装与本地版现场值均为 true / goto_main / stay_there，本轮未改动实际值。维护恢复工具的 settings 列表不包含这三项，更新迁移时保留用户值，不用新版默认值或减负建议替换。

1. 正常关闭任务和 WebUI，运行“备份本机配置”；记下当前本地验收标签。旧目录完整保留。
2. 在同级的新候选目录检出用户选择的上游提交。使用 `provenance.json` 的上游地址，手动联网拉取；不要在正在使用的目录运行 reset --hard、clean 或安装器。
3. 先读取新版 AGENTS / 配置定义；复制本地维护工具与启动关闭入口。运行 `maintain.py apply-source --root <候选目录>`，其补丁先 --check，冲突则停止。更新后已被上游改写的逻辑由 AI 根据本清单逐项迁移。
4. 将本机私有备份复制到候选的 `config/`，在候选目录通过新版 `ConfigUpdater.config_update()` 迁移并保存一次，再运行 `maintain.py apply --root <候选目录> --config alas2 --pause-monthly`。不要靠启动账号任务触发迁移；不从 GitHub 查找账号私有配置。
5. 有依赖变化时，用户允许的联网准备阶段运行 `uv sync --frozen --no-dev` / npm ci；待准备好再 `--offline` 验证。不改变旧目录环境。前端代码有变化时重新构建并写入 `deploy.frontend.source_fingerprint`。
6. 运行计时、启动、关闭和本地维护的针对性测试。建立新 manifest / 新提交 / 新验收标签，再在临时端口检查 /healthz、/ 和静态资源，确认外网拒绝，Run=null，游戏任务未自动运行；正常关闭并核对无 worker 残留。
7. 用户启用普通任务验证稳定后，再单独开启每月开荒；**智能调度必须一起复核**。遇到无法识别页面不要重复重启堆重试。
8. 私有 GitHub 只推运行源码、预构建前端、模型、配置模板、清单和恢复补丁；依据 `publish-targets.json` 核对目标，排除测试、mock与排查脚本，检查提交历史中也没有这些文件。完成真实配置/密钥扫描后推送新 main 和新验收标签。旧标签保留作为回退入口；回退时私有配置也使用对应日期备份，数据库不盲目覆盖。

原来的 `alas-launcher.exe` 单独作为 Release 附件备份。用于官方更新时，应放在独立候选安装目录，核对该目录的 Repository / Branch 指向用户选择的上游，联网准备后关闭启动器，再迁移本机修复与配置。当前上游 `deploy/git.py` / `deploy/Windows/git.py` 的仓库更新会执行 reset --hard；本地版 Repository 指向私人备份，直接在本地版运行启动器不能替代获取官方更新。日常继续使用本地 CMD 入口。Release 离线包与初始化步骤见 RELEASE_GUIDE.md。

## 最简现场检查

见 [QUICK_CHECK.md](QUICK_CHECK.md)。源码、配置、浏览器偏好、模拟器参数四处都可能变化；不能只检查一个 JSON 或把截图主观解读当日志事实。
