# 桌面界面与原设计

桌面窗口直接显示本地版已有 React WebUI，使用现有业务页面、主题、布局和配置；不是另一套重新设计的界面。桌面 WebView 与浏览器分别保留自己的页面偏好及登录存储，不读取或复制浏览器 Cookie。任务配置共用同一安装目录。

`desktop-titlebar.js` 的标题栏、四个窗口按钮、深浅主题跟随与退出选择器改编自 AzurPilotLauncher 2.2.4 的公开源码 `src/main.rs` 中 `main_window_titlebar_injection_script()`。原项目：<https://github.com/wess09/AzurPilotLauncher>，GPL-3.0，随附 `native/ORIGINAL-LAUNCHER-LICENSE.txt`。修改部分为受限的 WebView2 消息桥、本地退出提示、为原窗口按钮预留边距，以及隐藏仅用于网页的“关闭程序”入口。

原托盘图标沿用随包图标。托盘左键显示/隐藏；右键“显示 / 隐藏”“退出”。转入托盘销毁桌面 WebView，保留后台；恢复时重建窗口，等待首屏再淡入。“退出”请求身份核验后的正常关闭，不启动原 EXE 的自动更新、环境重建或端口清理流程。

原启动器的在线更新、开机自启代理和免密登录信任通道未接入新宿主；需要密码的安装仍使用原 WebUI 登录页。原 EXE 继续作为用户手动选择的更新工具备用。


窗口语义对照原 tauri.conf.json：splash 为 800×450、不可缩放且无系统装饰；main 为 1280×880、可缩放，src/main.rs 移除系统标题装饰。本地 .NET 宿主以 PerMonitorV2 manifest 保持原生 DPI 绘制，桌面保留 Windows 可缩放边框并移除系统标题栏，避免客户端命中补丁被 WebView 子窗口挡住。原界面标题栏代码继续复用。

r14 顶部非客户端处理参考原启动器依赖 Tao 0.33.0：src/platform_impl/windows/event_loop.rs 的 WM_NCCALCSIZE 与 util.rs 的 calculate_insets_for_dpi。Windows 无装饰阴影窗口保留侧/底框，顶部在 Windows 10 为零；原依赖来源 https://static.crates.io/crates/tao/tao-0.33.0.crate，Apache-2.0 许可证见 ../native/TAO-LICENSE.txt。微软自定义框架说明：https://learn.microsoft.com/en-us/windows/win32/dwm/customframe 。本地适配仅改宿主区域计算/视口同步，原标题栏和业务前端不替换。

r15 补齐同一 Tao 0.33.0 的最大化 rcWork 客户区与顶部 WM_NCHITTEST 语义。WinForms/WebView 子窗口适配仅增加顶部透明事件桥及还原尺寸保持；原标题栏样式继续复用，仅修正紧凑顶栏下的位置/尺寸。native/TAO-LICENSE.txt 保持原许可证，桌面注入脚本依旧遵循本文件前述 GPL-3.0 来源。

r16 在现有 Tao 式客户区计算外，补充 WinForms 宿主的 WM_GETMINMAXINFO 最大化限制，外框/客户区都限定为窗口所在显示器工作区，保留 Windows 任务栏。原标题栏和视频资源不变。

内嵌媒体使用独立的本机拦截域名 azurpilot-media.local，所有请求由宿主本地响应，不查询网络。文件映射域名不触发 WebResourceRequested，依据 Microsoft WebView2 官方文档：https://github.com/MicrosoftDocs/edge-developer/blob/main/microsoft-edge/webview2/how-to/webresourcerequested.md 。
