# 本地版统一启动器

根目录 `AzurPilot-Local.exe` 是固定入口。原生宿主使用 .NET Framework 与 WebView2，提供网页端和桌面端选择、配置备份、检查、更新与回退。

## 界面与资源

启动窗口为800×450逻辑像素，声明PerMonitorV2 DPI。底部小按钮点击后切换为左右排列的网页端/桌面端选项，下方返回。左上完整品牌图约116×93，距左22、距上17；右下品牌与版本，右上中断并退出。设置面板为半透明磨砂，打开与切页渐变过渡。

桌面端使用原项目界面、原标题栏关闭选择器及托盘逻辑。保留可缩放边框，最大化限定在显示器工作区。窄窗口仍显示主页旁的悬停工具。托盘隐藏销毁桌面 WebView，恢复时重建；后台继续运行。退出正常关闭本安装的后台，保留游戏与模拟器。

背景视频、MiSans、宋体按钮子集及 Cormorant 字体编译为 EXE 资源。媒体通过 `azurpilot-media.local` 流式提供并支持 Range；字体通过本机虚拟域名提供。正常播放不提前显示中间 poster，解码失败才显示备用图。

后台就绪后加载业务首屏并确认交接，启动器模糊淡出；桌面同步淡入，网页端则退出宿主。加载提示沿用原启动器小提示，不展示文件路径。

两种方式都先进入首页，不用上次的外观页覆盖落点。托盘恢复仍保留隐藏前的页面。正式包没有预置实例，维护实例选择器允许为空，初始化也不生成alas2或ap；用户从首页创建或导入。

加载期间可打开「查看启动日志」，失败后显示「错误详情」与真实异常，详情中可「保存日志」为本地TXT。维护页「启动诊断」也能打开最近启动记录。诊断包含原生/后端事件、stderr及GUI/WebUI日志，不依赖后台成功启动。详情允许显示原始路径，普通加载提示仍隐藏路径。

stdout与stderr读取结束后再判断最终状态，普通警告不作为失败信号。进程无结构化结果就退出时，也会结束加载并显示异常。Git校验允许慢磁盘、每10秒报告进度，并响应取消；运行服务仍保留正常的长等待能力。

## 版本目录

`Program.InstallRoot` 是固定 EXE 所在目录；`Program.Root` 由 `.updates/current.json` 解析为当前版本，无记录时使用安装根。单实例锁、settings.json、浏览器偏好和字体缓存归安装根；源码、运行环境、配置与交接票据归当前版本。

更新成功后先等待后端完成，再通过固定内部重启模式等待旧进程退出，重新打开根 EXE。重启参数不接受任意可执行路径。更新失败保持旧入口；回退恢复上一版本及对应数据。

## 后端协议

宿主只接受固定本机页面的消息，操作由白名单分发。后端启动命令显式传入当前版本根与 `AZURPILOT_INSTALL_ROOT`。

| 操作 | 作用 |
| --- | --- |
| inspect、check | 读取版本与检查状态 |
| start、stop | 启动/复用、正常停止本地服务 |
| initialize、restore | 初始化或主动恢复本地设置 |
| backup | 备份当前配置与业务数据 |
| check-update、update、rollback | 检查上游、独立构建验证并切换、回退 |
| prepare-candidate、patch、rebuild-runtime、rebuild-frontend | 折叠在手动维护中的分步操作 |

进度以 JSON 行输出，包含 job/action/phase/status/message/result。启动期间等待 stdin 的 handoff/cancel 消息；EOF 不取消后台。所有子命令 stdin=DEVNULL，防止控制读取线程与 Git 初始化互相阻塞。

本次新建服务取消时按 PID、创建时间和随机事件正常关闭；复用的旧服务保留。更新取消会终止本次构建命令并保留旧入口。涉及正常退出时沿用已有身份核验，不按进程名批量强杀。

首屏交接使用 95 秒有效的一次性票据；接口仅接受本机同源。它只确认页面就绪，不提供配置、任意路径或进程控制。默认本地启动不恢复记忆中的游戏任务。

## 构建

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File local-launcher/native/build.ps1 -EmbeddedVideoPath "background.mp4"
```

使用 Windows .NET Framework C# 编译器，需配套 WebView2 托管 DLL、x64 loader 和 ui 文件。视频为构建输入，发布包中无需外置副本。修改源码、资源或 EXE 后，重新验证并固定新标签、manifest 与 source.bundle。

原桌面设计来源见 [DESKTOP_SOURCES.md](ui/DESKTOP_SOURCES.md)，维护约定见 [AI_LOCAL_MAINTENANCE.md](../local-maintenance/AI_LOCAL_MAINTENANCE.md)。
