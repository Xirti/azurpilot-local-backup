# 启动器素材来源

- 当前视频：用户 2026-10-13 提供的桌面 `sakura.mp4`，原样复制为运行文件 `sakura-op.mp4`，没有重编码或覆盖桌面原件。33,073,048 字节，1920×1080、30fps、H.264 High、AAC，106.538333 秒；SHA256 `e95ddce86bac88ee4cc79e4c704e248a0fc3e8fc3406e42848ff64dc0c86dacc`。失败回退静态背景提取自该视频约 37 秒处；正常加载时隐藏，不作为开场封面。视频仅存本机，默认不加入源码 Git 历史；源码克隆后需自行补充视频，缺失时显示随包静态背景。
- 历史说明：原下载文件 SHA256 `78d94e569ddc7117f3b8499ce3631532fc242fefbb04b35b794926ac36c71e1f` 在约 93 秒后存在无效 NAL 数据。旧版曾使用 63,331,931 字节的重编码播放副本，现在已被上述新素材替换。旧下载原件保留，不能拿旧预览目录中的损坏文件覆盖当前视频。
- 图标、MiSansLauncher.ttf：用户本机原 AzurPilot 启动器的素材与字体，来自 alas-launcher 2.2.4 的公开源码目录。桌面标题栏源码改编另见 `../DESKTOP_SOURCES.md`。
- Cormorant Garamond：Google Fonts 的 `ofl/cormorantgaramond/CormorantGaramond[wght].ttf`；随附 `Cormorant-OFL.txt`。
- WebView2 SDK：Microsoft.Web.WebView2 1.0.3719.77，NuGet 官方包 `https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/1.0.3719.77/microsoft.web.webview2.1.0.3719.77.nupkg` 的 net462 托管程序集与 win-x64 loader；随附 native/LICENSE.txt。使用本机已有 WebView2 Runtime，启动不下载资源。

- 中文按钮字体：Noto Serif SC，来源 https://github.com/google/fonts/blob/main/ofl/notoserifsc/NotoSerifSC%5Bwght%5D.ttf。复用本机已存的官方源字体，固定 wght=500，按当前启动器文案与 ASCII 制作 WOFF2 子集，并重新命名为 AzurPilot Launcher Serif；随附 LauncherSerif-OFL.txt。新增按钮文案后应核对字体字符覆盖并补充子集，子集仅约 65 KB。
- 正文与加载提示：MiSansLauncher.woff2 是项目已有 frontend/public/MiSans-Demibold.ttf 的完整 WOFF2 转换，保留全部字符，替代原启动器不全的子集；未改动原 WebUI 字体。旧 MiSansLauncher.ttf 仅保留素材来源记录，运行改用完整 WOFF2。
- 加载小提示：改编自本机 alas-launcher 2.2.4 的 locales/zh-CN.yml 的 tips，保留其中 12 条适合本地版的提示。原启动器许可证见 ../../native/ORIGINAL-LAUNCHER-LICENSE.txt。
- MiSansLauncher.woff2、LauncherSerif.woff2、CormorantGaramond.ttf 由 native/build.ps1 直接嵌入 AzurPilot-Local.exe。宿主在 cache/local-launcher/fonts/<字体指纹>/ 恢复资源，校核损坏缓存后重写；字体请求由 WebView2 本机虚拟域名映射满足。清理缓存后下次启动可自行恢复。
