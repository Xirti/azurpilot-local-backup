// 原生窗口只接受本机界面的固定操作，Python 后端负责安装与维护语义。
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

static class Program {
    internal static EventWaitHandle ShowEvent;
    internal static string InstallRoot = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
    internal static string Root = InstallRoot;
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode)] static extern bool SetDllDirectory(string path);
    [DllImport("user32.dll")] static extern uint GetDpiForSystem();
    [DllImport("shell32.dll",CharSet=CharSet.Unicode)] static extern int SetCurrentProcessExplicitAppUserModelID(string id);
    [STAThread] static void Main(string[] args) {
        string entry=Path.Combine(InstallRoot,"AzurPilot-Local.exe");
        if(ManagedEntry.RelaunchHelper(args,entry))return;
        try{Root=ManagedEntry.Resolve(InstallRoot);}
        catch(Exception error){MessageBox.Show("无法打开当前版本："+error.Message,"AzurPilot");return;}
        string native = Path.Combine(Root, "local-launcher", "native");
        AppDomain.CurrentDomain.AssemblyResolve += delegate(object sender, ResolveEventArgs e) {
            string name = new AssemblyName(e.Name).Name;
            if (name != "Microsoft.Web.WebView2.Core" && name != "Microsoft.Web.WebView2.WinForms") return null;
            return Assembly.LoadFrom(Path.Combine(native, name + ".dll"));
        };
        SetDllDirectory(native);
        string key;
        using (SHA256 hash = SHA256.Create()) key = BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(InstallRoot.ToUpperInvariant()))).Replace("-", "").Substring(0, 24);
        SetCurrentProcessExplicitAppUserModelID("AzurPilot.Local."+key);
        bool created;
        using (Mutex single = new Mutex(true, "Local\\AzurPilotLauncher-" + key, out created)) {
            if (!created) {
                try{using(EventWaitHandle existing=EventWaitHandle.OpenExisting("Local\\AzurPilotLauncherShow-"+key))existing.Set();}
                catch(WaitHandleCannotBeOpenedException){MessageBox.Show("启动器正在打开，请稍等。", "AzurPilot");}
                return;
            }
            using(EventWaitHandle show=new EventWaitHandle(false,EventResetMode.AutoReset,"Local\\AzurPilotLauncherShow-"+key)) {
            ShowEvent=show;
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Run();
            }
        }
    }
    static void Run() { Application.Run(new LauncherForm()); }
    // 与原启动器一样，窗口尺寸以逻辑像素定义，渲染按当前屏幕 DPI 提供真实像素。
    internal static Size DisplaySize(int width,int height) {
        double scale=GetDpiForSystem()/96.0;
        return new Size((int)Math.Round(width*scale),(int)Math.Round(height*scale));
    }
}

sealed class LauncherForm : Form {
    [DllImport("user32.dll")] static extern bool ReleaseCapture();
    [DllImport("user32.dll")] static extern IntPtr SendMessage(IntPtr window, int message, IntPtr wParam, IntPtr lParam);
    const string Origin = "https://azurpilot-launcher.local";
    WebView2 view = new WebView2();
    JavaScriptSerializer json = new JavaScriptSerializer();
    Process job;
    string action = "";
    bool exiting, allowClose, complete, failed, restartRequested;
    string startUrl;
    string selectedMode="browser", selectedConfig="", handoffError, handoffPath, lastDesktopUrl;
    bool handoffStarted, handoffReady, desktopActive, closingDesktop, restoringDesktop;
    bool revealingDesktop, hideAfterReveal;
    CoreWebView2Environment environment;
    DesktopForm desktop;
    NotifyIcon tray;
    Icon trayImage;
    readonly LauncherDiagnostics diagnostics=new LauncherDiagnostics(Program.Root);
    bool readingDiagnostics;
    string stderrSummary="";
    System.Windows.Forms.Timer serviceWatch;
    int watchedPid;
    DateTime watchedStart;
    Rectangle? savedDesktopBounds;
    RegisteredWaitHandle showRegistration;
    readonly HashSet<string> actions = new HashSet<string>(new string[] {"inspect","start","initialize","check","backup","restore","prepare-candidate","patch","rebuild-frontend","rebuild-runtime","check-update","update","rollback"});
    string SettingsPath { get { return Path.Combine(Program.InstallRoot, "local-launcher", "settings.json"); } }
    public LauncherForm() {
        Text = "AzurPilot · 本地版";
        FormBorderStyle = FormBorderStyle.None;
        AutoScaleMode = AutoScaleMode.None;
        ClientSize = Program.DisplaySize(800, 450);
        MinimumSize = Program.DisplaySize(720, 405);
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Color.FromArgb(16, 18, 30);
        try { Icon = new Icon(Path.Combine(Program.Root, "local-launcher", "ui", "assets", "icon.ico"),new Size(64,64)); } catch (IOException) {}
        view.Dock = DockStyle.Fill; Controls.Add(view);
        Shown += async delegate { await Initialize(); };
        showRegistration=ThreadPool.RegisterWaitForSingleObject(Program.ShowEvent,delegate(object state,bool timeout){Ui(delegate{ShowRequested();});},null,-1,false);
        Resize += delegate { if (view != null && view.CoreWebView2 != null) Post(new {kind="visibility", hidden=WindowState == FormWindowState.Minimized}); };
        FormClosing += delegate(object sender, FormClosingEventArgs e) {
            if (desktopActive && !allowClose) {e.Cancel=true;HideToTray();return;}
            if (allowClose || job == null || job.HasExited) return;
            e.Cancel = true; ExitLauncher();
        };
        FormClosed += delegate {
            if(showRegistration!=null)showRegistration.Unregister(null);
            if (view!=null)view.Dispose();
            if (desktop!=null&&!desktop.IsDisposed)desktop.DestroyWindow();
            if (tray!=null){tray.Visible=false;tray.Dispose();}
            if (trayImage!=null)trayImage.Dispose();
            if (serviceWatch!=null)serviceWatch.Dispose();
            DeleteTicket();
        };
    }
    // 字体作为 EXE 资源保存；按内容指纹解出到私有缓存，不依赖系统安装字体。
    string EmbeddedFontDirectory() {
        string[] names={"MiSansLauncher.woff2","CormorantGaramond.ttf","LauncherSerif.woff2"};
        var fonts=new Dictionary<string,byte[]>();
        using(MemoryStream all=new MemoryStream()) {
            foreach(string name in names) {
                using(Stream resource=Assembly.GetExecutingAssembly().GetManifestResourceStream("AzurPilot.Fonts."+name)) {
                    if(resource==null)throw new InvalidOperationException("启动器内嵌字体缺失，请重新构建启动器。");
                    using(MemoryStream buffer=new MemoryStream()) {resource.CopyTo(buffer);fonts[name]=buffer.ToArray();all.Write(fonts[name],0,fonts[name].Length);}
                }
            }
            string key;
            using(SHA256 hash=SHA256.Create())key=BitConverter.ToString(hash.ComputeHash(all.ToArray())).Replace("-", "").Substring(0,24);
            string directory=Path.Combine(Program.InstallRoot,"cache","local-launcher","fonts",key);
            Directory.CreateDirectory(directory);
            foreach(string name in names) {
                string path=Path.Combine(directory,name);
                bool matches=false;
                if(File.Exists(path))using(SHA256 hash=SHA256.Create())using(Stream cached=File.OpenRead(path)) {
                    byte[] actual=hash.ComputeHash(cached),expected=hash.ComputeHash(fonts[name]);
                    matches=BitConverter.ToString(actual)==BitConverter.ToString(expected);
                }
                if(!matches)File.WriteAllBytes(path,fonts[name]);
            }
            return directory;
        }
    }
    async Task Initialize() {
        try {
            var options = new CoreWebView2EnvironmentOptions();
            options.AdditionalBrowserArguments = "--autoplay-policy=no-user-gesture-required";
            // 调试端口只由本机验证者显式传入，默认不监听调试端口。
            int port;
            if (Int32.TryParse(Environment.GetEnvironmentVariable("AZURPILOT_LAUNCHER_DEBUG_PORT"), out port) && port >= 1024 && port <= 65535)
                options.AdditionalBrowserArguments += " --remote-debugging-port=" + port;
            environment = await CoreWebView2Environment.CreateAsync(null, Path.Combine(Program.InstallRoot, "cache", "local-launcher", "webview"), options);
            await view.EnsureCoreWebView2Async(environment);
            view.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
            view.CoreWebView2.Settings.AreDevToolsEnabled = false;
            view.CoreWebView2.Settings.IsStatusBarEnabled = false;
            view.CoreWebView2.Settings.IsWebMessageEnabled = true;
            view.CoreWebView2.SetVirtualHostNameToFolderMapping("azurpilot-launcher.local", Path.Combine(Program.Root,"local-launcher","ui"), CoreWebView2HostResourceAccessKind.DenyCors);
            view.CoreWebView2.SetVirtualHostNameToFolderMapping("azurpilot-fonts.local", EmbeddedFontDirectory(), CoreWebView2HostResourceAccessKind.Allow);
            view.CoreWebView2.NavigationStarting += delegate(object sender, CoreWebView2NavigationStartingEventArgs e) { if (!Trusted(e.Uri)) e.Cancel = true; };
            view.CoreWebView2.NewWindowRequested += delegate(object sender, CoreWebView2NewWindowRequestedEventArgs e) { e.Handled = true; };
            view.CoreWebView2.PermissionRequested += delegate(object sender, CoreWebView2PermissionRequestedEventArgs e) { e.State = CoreWebView2PermissionState.Deny; };
            view.CoreWebView2.DownloadStarting += delegate(object sender, CoreWebView2DownloadStartingEventArgs e) { e.Cancel = true; };
            view.CoreWebView2.WebMessageReceived += Receive;
            EmbeddedMedia.Attach(view,environment,Origin);
            view.CoreWebView2.Navigate(Origin + "/index.html");
        } catch (Exception e) {
            MessageBox.Show("启动器界面无法加载：" + e.Message + "\n请检查 WebView2 运行时，或重新解压完整发布目录。", "AzurPilot", MessageBoxButtons.OK, MessageBoxIcon.Error);
            allowClose = true; Close();
        }
    }
    static bool Trusted(string value) {
        Uri uri;
        return Uri.TryCreate(value, UriKind.Absolute, out uri) && uri.Scheme == "https" && uri.Host == "azurpilot-launcher.local" && uri.Port == 443;
    }
    void Post(object value) {
        if (!IsDisposed && view != null && view.CoreWebView2 != null) view.CoreWebView2.PostWebMessageAsJson(json.Serialize(value));
    }
    string Field(Dictionary<string, object> data, string name, string fallback) {
        object value; return data.TryGetValue(name, out value) && value is string ? (string)value : fallback;
    }
    async void Receive(object sender, CoreWebView2WebMessageReceivedEventArgs e) {
        if (!Trusted(e.Source)) return;
        try {
            var data = json.Deserialize<Dictionary<string, object>>(e.WebMessageAsJson);
            string command = Field(data, "command", "");
            if (command == "ready") {
                object settings = new Dictionary<string, object>();
                if (File.Exists(SettingsPath)) {
                    try { settings = json.DeserializeObject(File.ReadAllText(SettingsPath, Encoding.UTF8)); }
                    catch (ArgumentException) { settings = new Dictionary<string, object>(); }
                }
                Post(new {kind="settings", settings=settings}); await RunJob("inspect", data);
            } else if (command == "action") {
                string requested = Field(data,"action","");
                if (!actions.Contains(requested)) throw new InvalidOperationException("不支持的操作。");
                if (job != null) throw new InvalidOperationException("请等待当前操作完成。");
                await RunJob(requested, data);
            } else if (command == "exit") ExitLauncher();
            else if (command == "diagnostics") {
                if(readingDiagnostics)return;readingDiagnostics=true;
                try{string detail=await Task.Run(()=>diagnostics.Read());if(detail.Length>300000)detail=detail.Substring(0,100000)+"\n…\n"+detail.Substring(detail.Length-200000);Post(new{kind="diagnostics",text=detail});}
                finally{readingDiagnostics=false;}
            }
            else if (command == "save-log") {
                using(var dialog=new SaveFileDialog()) {
                    dialog.Title="保存启动诊断日志";dialog.Filter="文本日志 (*.txt)|*.txt";
                    dialog.FileName="AzurPilot-启动日志-"+DateTime.Now.ToString("yyyyMMdd-HHmmss")+".txt";
                    if(dialog.ShowDialog(this)==DialogResult.OK){diagnostics.Save(dialog.FileName);Post(new{kind="log-saved",message="启动日志已保存。"});}
                }
            }
            else if (command == "drag") { ReleaseCapture(); SendMessage(Handle,0xA1,new IntPtr(2),IntPtr.Zero); }
            else if (command == "settings") SaveSettings(data);
            else if (command == "folder") {
                if (job != null) return;
                using (FolderBrowserDialog folder = new FolderBrowserDialog()) {
                    folder.Description = "选择独立候选目录；获取官方版本时目录必须为空";
                    folder.ShowNewFolderButton = true;
                    if (folder.ShowDialog(this) == DialogResult.OK) Post(new {kind="folder", path=folder.SelectedPath});
                }
            }
        } catch (Exception error) { diagnostics.Append(error.ToString());Post(new {kind="error", message=error.Message}); }
    }
    void SaveSettings(Dictionary<string,object> data) {
        int volume; if (!Int32.TryParse(Field(data,"volume","25"), out volume)) volume = 25;
        var settings = new {volume=Math.Max(0,Math.Min(100,volume)), muted=Field(data,"muted","true") == "true", fit=Field(data,"fit","cover") == "contain" ? "contain" : "cover", config=Field(data,"config","")};
        string temporary = SettingsPath + ".tmp";
        File.WriteAllText(temporary,json.Serialize(settings), new UTF8Encoding(false));
        if (File.Exists(SettingsPath)) File.Replace(temporary, SettingsPath, null); else File.Move(temporary, SettingsPath);
    }
    // Windows CreateProcess 参数转义；始终关闭 shell，不接受前端命令字符串。
    static string Quote(string value) {
        StringBuilder result = new StringBuilder("\""); int slashes = 0;
        foreach (char c in value) {
            if (c == '\\') { slashes++; continue; }
            if (c == '"') { result.Append('\\', slashes * 2 + 1); result.Append(c); }
            else { result.Append('\\', slashes); result.Append(c); }
            slashes = 0;
        }
        result.Append('\\', slashes * 2); result.Append('"'); return result.ToString();
    }
    string Python() {
        string metadata=Path.Combine(Program.Root,"local-maintenance","offline-artifacts","release-runtime.json");
        if(File.Exists(metadata)) {
            var runtime=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(metadata,Encoding.UTF8));
            string relative=Field(runtime,"runtime_python","");
            if(relative.StartsWith("python-runtime/",StringComparison.Ordinal)&&relative.IndexOf("..",StringComparison.Ordinal)<0) {
                string resolved=Path.GetFullPath(Path.Combine(Program.Root,relative.Replace('/',Path.DirectorySeparatorChar)));
                if(resolved.StartsWith(Program.Root+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)&&File.Exists(resolved))return resolved;
            }
        }
        string runtimes = Path.Combine(Program.Root,"python-runtime");
        if (Directory.Exists(runtimes)) {
            foreach (string directory in Directory.GetDirectories(runtimes,"cpython-*-windows-x86_64-none")) {
                string python = Path.Combine(directory,"python.exe"); if (File.Exists(python)) return python;
            }
        }
        string fallback = Path.Combine(Program.Root,".venv","Scripts","python.exe");
        if (File.Exists(fallback)) return fallback;
        throw new FileNotFoundException("随包 Python 环境缺失，请解压完整离线包。");
    }
    async Task RunJob(string requested, Dictionary<string,object> data) {
        if(requested!="inspect")diagnostics.Begin(requested,Field(data,"mode",selectedMode));
        string python = Python();
        if (requested=="start") {
            selectedMode=Field(data,"mode","browser");
            if(selectedMode!="browser"&&selectedMode!="desktop")throw new InvalidOperationException("请选择网页端或桌面端。");
            selectedConfig=Field(data,"config","");handoffStarted=false;handoffReady=false;handoffError=null;
        }
        action=requested; complete=false; failed=false;restartRequested=false;stderrSummary="";if(requested=="start")startUrl=null;
        Post(new {kind="job", action=action});
        Process process = new Process(); job=process;
        var info = new ProcessStartInfo(python);
        info.Arguments = "-X utf8 " + Quote(Path.Combine(Program.Root,"local-launcher","backend.py")) + " " + requested + " --root " + Quote(Program.Root)
            + " --config " + Quote(Field(data,"config","")) + " --candidate " + Quote(Field(data,"candidate","")) + " --reference " + Quote(Field(data,"reference",""));
        if(requested=="start")info.Arguments += " --wait-handoff";
        info.WorkingDirectory=Program.Root; info.UseShellExecute=false; info.CreateNoWindow=true;
        info.RedirectStandardOutput=true; info.RedirectStandardError=true; info.RedirectStandardInput=true;
        info.StandardOutputEncoding=Encoding.UTF8; info.StandardErrorEncoding=Encoding.UTF8;
        info.EnvironmentVariables["PYTHONUTF8"]="1";
        info.EnvironmentVariables["AZURPILOT_INSTALL_ROOT"]=Program.InstallRoot;
        foreach(string name in new[]{"PYTHONHOME","PYTHONPATH","VIRTUAL_ENV","__PYVENV_LAUNCHER__"})info.EnvironmentVariables.Remove(name);
        process.StartInfo=info;
        try {
            process.Start();
            await Task.WhenAll(ReadProgress(process.StandardOutput),ReadErrors(process.StandardError),Task.Run(delegate { process.WaitForExit(); }));
            if (!complete||(process.ExitCode!=0&&!failed)) {
                complete=true;failed=true;
                Post(new {kind="error", message="后台已退出（退出码 " + process.ExitCode + "）"+(String.IsNullOrEmpty(stderrSummary)?"，请查看启动日志。":"："+stderrSummary)});
            }
            if (exiting) { if(desktop!=null)desktop.DestroyWindow();allowClose=true; Close(); }
            else if (requested=="start" && complete && !failed && startUrl != null) {
                if(handoffReady)await FinishHandoff();
                else Post(new {kind="error",message="页面交接没有完成，请重试。"});
            }
            else if(requested=="start" && !String.IsNullOrEmpty(handoffError))Post(new {kind="error",message=handoffError});
            if(requested=="start"&&!handoffReady&&desktop!=null){desktop.DestroyWindow();desktop=null;TopMost=false;}
        } finally {
            if(requested=="start") {
                DeleteTicket();
                if(!desktopActive&&desktop!=null){desktop.DestroyWindow();desktop=null;TopMost=false;}
            }
            job=null; action=""; process.Dispose();
        }
        if(!exiting&&complete&&!failed&&restartRequested) {
            Post(new{kind="restarting",message="版本已就绪，正在重新打开启动器…"});
            await Task.Delay(200);
            ManagedEntry.RestartAfterExit(Path.Combine(Program.InstallRoot,"AzurPilot-Local.exe"));
            await Fade(this,1,0,300);
            allowClose=true;Close();
        }
    }
    async Task ReadProgress(StreamReader output) {
        string line;while((line=await output.ReadLineAsync())!=null)OnLine(line);
    }
    async Task ReadErrors(StreamReader output) {
        string line;while((line=await output.ReadLineAsync())!=null){diagnostics.Append("[stderr] "+line);if(!String.IsNullOrWhiteSpace(line))stderrSummary=line.Substring(0,Math.Min(line.Length,1200));Post(new{kind="diagnostic-line",text=line});}
    }
    void Ui(Action action) { if (!IsDisposed && IsHandleCreated) BeginInvoke(action); }
    void OnLine(string line) {
        diagnostics.Append(line);
        try {
            var record=json.Deserialize<Dictionary<string,object>>(line);
            diagnostics.Track(Field(record,"log_path",""));
            string phase=Field(record,"phase","");
            object payload;
            if(record.TryGetValue("result",out payload)&&payload is Dictionary<string,object>) {
                var fields=(Dictionary<string,object>)payload;object restart;
                if(fields.TryGetValue("restart_required",out restart)&&restart is bool)restartRequested=(bool)restart;
                string url=Field(fields,"url","");Uri parsed;
                if(Uri.TryCreate(url,UriKind.Absolute,out parsed)&&parsed.Scheme=="http"&&parsed.Host=="127.0.0.1"&&String.IsNullOrEmpty(parsed.UserInfo))startUrl=url;
            }
            if (phase=="complete" || phase=="failed" || phase=="cancelled") {
                complete=true; failed=Field(record,"status","") != "succeeded";
                object result;
                if (record.TryGetValue("result",out result) && result is Dictionary<string,object>) {
                    var fields=(Dictionary<string,object>)result;
                    string url=Field(fields,"url",""); Uri parsed;
                    if (Uri.TryCreate(url,UriKind.Absolute,out parsed) && parsed.Scheme=="http" && parsed.Host=="127.0.0.1" && String.IsNullOrEmpty(parsed.UserInfo)) startUrl=url;
                }
            }
            Post(new {kind="event", record=record});
            if(phase=="ready"&&action=="start"&&!handoffStarted){handoffStarted=true;BeginHandoff();}
        } catch (ArgumentException) { Post(new {kind="diagnostic-line", text=line}); }
    }
    void ExitLauncher() {
        if (exiting) return;
        if (job == null || job.HasExited) { allowClose=true; Close(); return; }
        exiting=true;
        if ((action=="start"||action=="update"||action=="rollback") && !complete) {
            Post(new {kind="exiting", message="正在中断本次启动…"});
            ControlStartup("cancel");
        } else Post(new {kind="exiting", message="等待当前维护操作完成后退出…"});
    }

    sealed class LocalClient : WebClient {
        protected override WebRequest GetWebRequest(Uri address) {var request=base.GetWebRequest(address);request.Proxy=null;request.Timeout=3000;return request;}
    }
    string CreateTicket(string fragment) {
        DeleteTicket();
        string folder=Path.Combine(Program.Root,"cache","local-launcher","handoff");Directory.CreateDirectory(folder);
        foreach(string path in Directory.GetFiles(folder,"*.json")) {
            Guid parsed;
            if(Guid.TryParseExact(Path.GetFileNameWithoutExtension(path),"N",out parsed)&&File.GetLastWriteTimeUtc(path)<DateTime.UtcNow.AddMinutes(-5))try{File.Delete(path);}catch(IOException){}
        }
        string ticket=Guid.NewGuid().ToString("N");handoffPath=Path.Combine(folder,ticket+".json");
        DateTime epoch=new DateTime(1970,1,1,0,0,0,DateTimeKind.Utc);
        using(Process self=Process.GetCurrentProcess()) {
            var record=new{protocol=1,state="waiting",expires_at=(DateTime.UtcNow.AddSeconds(95)-epoch).TotalSeconds,owner_pid=self.Id,owner_created_at=(self.StartTime.ToUniversalTime()-epoch).TotalSeconds};
            File.WriteAllText(handoffPath,json.Serialize(record),new UTF8Encoding(false));
        }
        return startUrl.TrimEnd('/')+"/?launcher_handoff="+ticket+fragment;
    }
    void DeleteTicket() {if(handoffPath!=null){try{File.Delete(handoffPath);}catch(IOException){}handoffPath=null;}}
    async Task WaitForPage() {
        Stopwatch watch=Stopwatch.StartNew();
        while(watch.Elapsed.TotalSeconds<90) {
            if(exiting||IsDisposed)throw new OperationCanceledException();
            try {
                var record=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(handoffPath));
                if(Field(record,"state","")=="ready")return;
            }catch(IOException){}catch(ArgumentException){}
            await Task.Delay(100);
        }
        throw new TimeoutException("后续页面尚未确认就绪，请检查网页加载状态后重试。");
    }
    void ControlStartup(string command) {
        try{if(job==null||job.HasExited)return;job.StandardInput.WriteLine(command);job.StandardInput.Flush();}
        catch(IOException){}catch(InvalidOperationException){}
    }
    async void BeginHandoff() {
        try {
            if(String.IsNullOrEmpty(startUrl))throw new InvalidOperationException("没有收到有效的本机 WebUI 地址。");
            string capability=await Task.Run(delegate{using(var client=new LocalClient())return client.DownloadString(startUrl+"/api/local-launcher/handoff");});
            if(exiting||IsDisposed)return;
            var supported=json.Deserialize<Dictionary<string,object>>(capability);
            if(!supported.ContainsKey("protocol")||Convert.ToInt32(supported["protocol"])!=1)throw new InvalidOperationException("WebUI 不支持界面交接。");
            string url=CreateTicket("#/");
            TopMost=true;
            if(selectedMode=="desktop") {
                desktop=new DesktopForm(startUrl,Icon,HideToTray,QuitDesktop);
                await desktop.Prepare(environment,url);
            }else Process.Start(new ProcessStartInfo(url){UseShellExecute=true});
            await WaitForPage();
            if(exiting)return;
            handoffReady=true;ControlStartup("handoff");
        }catch(Exception error) {
            handoffError="界面交接未完成："+error.Message+" 已有旧版 WebUI 时，请先正常关闭后重新启动。";
            handoffReady=false;ControlStartup("cancel");TopMost=false;
        }
    }
    static async Task Fade(Form window,double from,double to,int milliseconds) {
        Stopwatch watch=Stopwatch.StartNew();
        while(!window.IsDisposed&&watch.ElapsedMilliseconds<milliseconds) {
            double fraction=(double)watch.ElapsedMilliseconds/milliseconds;fraction=fraction*fraction*(3-2*fraction);
            window.Opacity=from+(to-from)*fraction;await Task.Delay(16);
        }
        if(!window.IsDisposed)window.Opacity=to;
    }
    async Task FinishHandoff() {
        Post(new{kind="handoff",message=selectedMode=="desktop"?"正在进入桌面端…":"正在进入网页端…"});
        await Task.Delay(160);
        if(IsDisposed)return;
        if(selectedMode=="desktop") {
            DesktopForm target=desktop;
            revealingDesktop=true;hideAfterReveal=false;
            try {
                ConfigureDesktop();target.BeginReveal();
                await Task.WhenAll(Fade(this,1,0,600),Fade(target,0,1,600));
                if(IsDisposed)return;
                Hide();TopMost=false;ShowInTaskbar=false;
                if(view!=null){Controls.Remove(view);view.Dispose();view=null;}
                revealingDesktop=false;
                if(hideAfterReveal)HideToTray();
                else if(desktop==target&&!target.IsDisposed)target.Activate();
            }finally{revealingDesktop=false;}
        }else {await Fade(this,1,0,600);allowClose=true;Close();}
    }
    void ConfigureDesktop() {
        var record=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(Path.Combine(Program.Root,"cache","webui-workers.json")));
        watchedPid=Convert.ToInt32(record["owner_pid"]);
        using(Process process=Process.GetProcessById(watchedPid))watchedStart=process.StartTime.ToUniversalTime();
        DateTime epoch=new DateTime(1970,1,1,0,0,0,DateTimeKind.Utc);
        if(Math.Abs((watchedStart-epoch).TotalSeconds-Convert.ToDouble(record["owner_created_at"]))>.05)throw new InvalidOperationException("后台身份登记不匹配。");
        desktopActive=true;lastDesktopUrl=desktop.CurrentUrl;
        var menu=new ContextMenuStrip();
        var toggle=new ToolStripMenuItem("显示 / 隐藏");
        toggle.Click += async delegate {try{if(desktop!=null&&!desktop.IsDisposed&&desktop.Visible)HideToTray();else await RestoreDesktop();}catch(Exception error){MessageBox.Show(error.Message,"AzurPilot");}};
        var quitItem=new ToolStripMenuItem("退出");
        quitItem.Click += async delegate {try{await QuitDesktop();}catch(Exception error){MessageBox.Show(error.Message,"AzurPilot");}};
        menu.Items.Add(toggle);menu.Items.Add(new ToolStripSeparator());menu.Items.Add(quitItem);
        trayImage=new Icon(Path.Combine(Program.Root,"local-launcher","ui","assets","icon.ico"),SystemInformation.SmallIconSize);
        tray=new NotifyIcon{Icon=trayImage,Text="AzurPilot · 本地版",ContextMenuStrip=menu,Visible=true};
        tray.MouseClick += async delegate(object sender,MouseEventArgs e){if(e.Button!=MouseButtons.Left)return;try{if(desktop!=null&&!desktop.IsDisposed&&desktop.Visible)HideToTray();else await RestoreDesktop();}catch(Exception error){MessageBox.Show(error.Message,"AzurPilot");}};
        serviceWatch=new System.Windows.Forms.Timer{Interval=2000};serviceWatch.Tick += delegate {WatchService();};serviceWatch.Start();
    }
    void HideToTray() {
        if(desktop==null||desktop.IsDisposed||closingDesktop||restoringDesktop)return;
        if(revealingDesktop){hideAfterReveal=true;return;}
        lastDesktopUrl=desktop.CurrentUrl;if(desktop.WindowState==FormWindowState.Normal)savedDesktopBounds=desktop.Bounds;
        desktop.DestroyWindow();desktop=null;
    }
    async Task RestoreDesktop() {
        if(restoringDesktop||closingDesktop)return;
        if(desktop!=null&&!desktop.IsDisposed){desktop.WindowState=FormWindowState.Normal;desktop.Show();desktop.Activate();return;}
        restoringDesktop=true;
        try {
            string fragment=String.IsNullOrEmpty(lastDesktopUrl)?"#/":new Uri(lastDesktopUrl).Fragment;
            string url=CreateTicket(fragment);
            desktop=new DesktopForm(startUrl,Icon,HideToTray,QuitDesktop);
            if(savedDesktopBounds.HasValue){desktop.StartPosition=FormStartPosition.Manual;desktop.Bounds=savedDesktopBounds.Value;}
            await desktop.Prepare(environment,url);await WaitForPage();desktop.BeginReveal();await Fade(desktop,0,1,300);desktop.Activate();
        }catch{if(desktop!=null){desktop.DestroyWindow();desktop=null;}throw;}
        finally{DeleteTicket();restoringDesktop=false;}
    }
    async void ShowRequested() {
        try {
            if(desktopActive)await RestoreDesktop();
            else {WindowState=FormWindowState.Normal;Show();Activate();}
        }catch(Exception error){MessageBox.Show(error.Message,"AzurPilot");}
    }
    async Task QuitDesktop() {
        if(closingDesktop)return;
        if(job!=null||restoringDesktop)throw new InvalidOperationException("界面正在交接，请稍后再退出。");
        closingDesktop=true;
        try {
            await RunJob("stop",new Dictionary<string,object>());
            if(!complete||failed)throw new InvalidOperationException("后台尚未确认正常关闭，请查看本次日志。");
            allowClose=true;Close();
        }finally{closingDesktop=false;}
    }
    void WatchService() {
        if(closingDesktop||IsDisposed)return;
        bool alive;
        try{using(Process process=Process.GetProcessById(watchedPid))alive=!process.HasExited&&process.StartTime.ToUniversalTime()==watchedStart;}
        catch(ArgumentException){alive=false;}
        catch(System.ComponentModel.Win32Exception){return;}
        catch(InvalidOperationException){return;}
        if(alive)return;
        try {
            var registry=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(Path.Combine(Program.Root,"cache","webui-workers.json")));
            if(((Dictionary<string,object>)registry["workers"]).Count>0)return;
            allowClose=true;Close();
        }catch(IOException){}catch(ArgumentException){}
    }
}
