# 本机断网版构建与恢复

## 已验证的范围

使用当前 Windows x64 / CPython3.14.6 的缓存执行 `uv sync --frozen --offline --no-dev`，成功安装142个运行依赖。包含开发依赖的同一命令失败于缺少 pandas3.0.6缓存；普通运行不需要这项开发依赖。缓存状态未来会变，不能假设任意电脑、任意新版都已具备这些包。

前端使用已安装的 Node 和 node_modules 执行 `npm --offline run build --prefix frontend`，生产构建成功；构建只读复用旧安装的依赖目录。运行时不需要 Node / node_modules，GitHub 保存 `frontend/dist` 与内容指纹。更换前端依赖后需重新准备锁文件对应的 node_modules，不能据这次成功保证冷机 npm ci --offline 能成功。

本地版基础 CPython 已复制到自己的 `python-runtime/` 并核对 base_prefix；基础解释器放在虚拟环境之外，重建 .venv 不会擦掉它，避免依赖旧安装的解释器；`.venv` 仍只保留在本机。移动根目录需要按新路径重建虚拟环境，不能承诺把旧 `.venv` 拷贝到任意位置就可用。

## 三类使用情形

Windows 重建入口使用 `python-runtime/tools/uv.exe`，将 uv 放在被重建的 `.venv` 之外。直接从 `.venv/Scripts/uv.exe` 发起环境重建会因正在运行的可执行文件被占用而失败；本轮已复现并调整入口。基础 Python 同样放在 `python-runtime/`，更新或重建虚拟环境不会删除它。

| 情形 | 需要什么 | 做法 |
| --- | --- | --- |
| 已准备好的本地版，外网断开 | `.venv`、源码、frontend/dist、模型、私人配置 | 直接“启动WebUI_无限等待.cmd”；缺产物报错，不自动下载 |
| 本机更新后从缓存重建 | 本地 CPython、uv、完整且匹配锁文件的运行依赖缓存 | 正常关闭后运行“手动重建运行环境.ps1”；其 --offline --no-dev 缺包就停止 |
| 新电脑完全离线安装 | 提前准备同平台 Python+uv、所有运行依赖缓存/离线包、匹配dist、模型和私人配置 | 在联网准备阶段先验证 --offline 重建，再把所需材料另存离线介质；GitHub源码本身不是完整安装环境 |

## 人工准备命令

联网准备由用户决定。不要写入自动启动入口，且不要在原安装目录升级。

```powershell
# 候选目录，手动准备新版本依赖
uv sync --frozen --no-dev
npm ci --prefix frontend --no-audit --no-fund
npm run build --prefix frontend

# 构建完成后写源码指纹；此命令不自动安装 npm 依赖
.\.venv\Scripts\python.exe -X utf8 -c 'from deploy.frontend import source_fingerprint; from pathlib import Path; p=Path("frontend"); (p/"dist/.source-fingerprint").write_text(source_fingerprint(p)+"\n", encoding="utf-8")'

# 缓存验证，显式禁止 Python 自动下载
$env:UV_PYTHON_DOWNLOADS = 'never'
uv sync --frozen --offline --no-dev --python <已准备的Python路径>
```

uv缓存路径用 `uv cache dir` 查询，Python使用项目 `python-runtime/` 里的版本。不要运行 uv cache clean / prune 清掉仍想保留的离线依赖；uv不保证“曾经安装过”就永远可离线重装，缓存可能缺失或有失效项。[uv官方缓存说明](https://docs.astral.sh/uv/concepts/cache/)

## 网络范围

“本地版”表示 WebUI 和识别服务在本机使用，不自动检查/应用更新、不建立远程隧道、不注入网页 Clarity。固定启动入口向Python子进程注入本地限制，拒绝标准 socket 的非回环 DNS/连接；页面CSP限制其自动请求。它不是系统级防火墙，也不关闭电脑网卡。

碧蓝航线登录、加载在线数据和实际任务需要连接游戏服务器。本机 ADB 与 MuMu IPC是局部通道；本轮没有启动游戏或验证游戏在断网情况下可作战。消息推送、LLM、外部统计上传等外网功能在本地模式下不可用；要保留这些功能就需要单独设计联网模式。

## GitHub备份内容

包括运行源码、已有修复、生产前端、跟踪的OCR模型、GPL许可证、维护清单和可审阅补丁。按用户要求，测试、mock、测试配置、开发排查脚本和CI不上传，也不进入提交历史；本机保留验证材料。排除真实config、access password、通知key、LLMkey、模拟器标识、日志、截图、数据库、PID/关闭事件回执、venv、node_modules与缓存。

生产前端指纹忽略测试与mock文件；从备份检出后不要求存在本机测试目录。需要生成新配置/API/图像模板时，在用户选定的上游候选目录保留相应生成器，验证通过后只把运行源文件和对应生成产物带回本机版。

本次最大模型小于100MiB，因此可在普通Git提交中备份。完整Python运行环境和缓存较大，另存本机/离线介质，未来若需要上传应另行准备无私人数据的release包。[GitHub文件限制说明](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)

从GitHubclone时：先读本维护清单，再准备Python和依赖，恢复自己的私人config，运行逐项本地设置恢复，确认验收标签存在并匹配HEAD，最后启动。代码可以从GitHub恢复，账号状态不能从这份源码仓库恢复。
