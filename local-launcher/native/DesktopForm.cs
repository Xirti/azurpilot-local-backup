// 复用本地 WebUI 和原桌面标题栏；窗口桥只处理明确的窗口操作。
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

sealed class DesktopForm : Form {
    [DllImport("user32.dll")] static extern bool ReleaseCapture();
    [DllImport("user32.dll")] static extern IntPtr SendMessage(IntPtr window,int message,IntPtr wParam,IntPtr lParam);
    [DllImport("user32.dll")] static extern uint GetDpiForWindow(IntPtr window);
    [DllImport("user32.dll")] static extern int GetSystemMetricsForDpi(int index,uint dpi);
    [DllImport("user32.dll")] static extern bool IsZoomed(IntPtr window);
    [DllImport("user32.dll")] static extern bool IsIconic(IntPtr window);
    [StructLayout(LayoutKind.Sequential)] struct WindowPosition {
        public IntPtr window,insertAfter;
        public int x,y,width,height;
        public uint flags;
    }
    [StructLayout(LayoutKind.Sequential)] struct MinMaxInfo {
        public Point reserved,maxSize,maxPosition,minTrackSize,maxTrackSize;
    }
    readonly Uri origin;
    readonly Action hide;
    readonly Func<Task> quit;
    readonly JavaScriptSerializer json = new JavaScriptSerializer();
    WebView2 view = new WebView2();
    bool forceClose, preparing = true;
    Rectangle lastNormalBounds;
    bool restoreFromMaximized,restoreQueued;
    public string CurrentUrl { get { return view.CoreWebView2 == null ? origin.ToString() : view.CoreWebView2.Source; } }
    protected override bool ShowWithoutActivation { get { return preparing; } }
    public DesktopForm(string url, Icon icon, Action hide, Func<Task> quit) {
        origin = new Uri(url); this.hide=hide;this.quit=quit;
        Text="AzurPilot · 本地版"; Icon=icon; FormBorderStyle=FormBorderStyle.Sizable;
        AutoScaleMode=AutoScaleMode.None;
        Size area=Screen.PrimaryScreen.WorkingArea.Size;
        Size desired=Program.DisplaySize(1280,880),margin=Program.DisplaySize(40,40);
        // 按外框限制在工作区内，避免无系统标题栏时客户端尺寸换算加入额外高度。
        Size=new Size(Math.Min(desired.Width,area.Width-margin.Width),Math.Min(desired.Height,area.Height-margin.Height));
        MinimumSize=Program.DisplaySize(900,620);
        StartPosition=FormStartPosition.CenterScreen; BackColor=Color.FromArgb(24,28,36);
        Opacity=0;ShowInTaskbar=false;view.DefaultBackgroundColor=BackColor;view.Dock=DockStyle.Fill;Controls.Add(view);
        FormClosing += delegate(object sender,FormClosingEventArgs e) {
            if(forceClose)return;e.Cancel=true;
            if(view.CoreWebView2!=null) { var pending=view.CoreWebView2.ExecuteScriptAsync("if(window.__ALAS_OPEN_CLOSE_PROMPT)window.__ALAS_OPEN_CLOSE_PROMPT();"); }
            else hide();
        };
        FormClosed += delegate {view.Dispose();};
    }
    bool Trusted(string value) {
        Uri uri;
        return Uri.TryCreate(value,UriKind.Absolute,out uri) && uri.Scheme==origin.Scheme && uri.Host=="127.0.0.1" && uri.Port==origin.Port && String.IsNullOrEmpty(uri.UserInfo);
    }
    protected override CreateParams CreateParams {
        get {
            CreateParams parameters=base.CreateParams;
            // 保留 Windows 原生侧/底可缩放边框，顶部由 Tao 式命中处理和 WebView 桥接。
            parameters.Style &= ~0x00C00000;
            return parameters;
        }
    }
    protected override void WndProc(ref Message message) {
        if(message.Msg==0x24) {
            base.WndProc(ref message);
            // 普通浏览器式最大化：外框也止于工作区，不能用不可见边框覆盖任务栏。
            Screen screen=Screen.FromHandle(Handle);
            Rectangle area=screen.WorkingArea,monitor=screen.Bounds;
            MinMaxInfo limits=(MinMaxInfo)Marshal.PtrToStructure(message.LParam,typeof(MinMaxInfo));
            limits.maxPosition=new Point(area.Left-monitor.Left,area.Top-monitor.Top);
            limits.maxSize=new Point(area.Width,area.Height);
            Marshal.StructureToPtr(limits,message.LParam,false);
            return;
        }
        if(message.Msg==0x46&&restoreFromMaximized&&!lastNormalBounds.IsEmpty&&!IsZoomed(Handle)&&!IsIconic(Handle)) {
            // WinForms 的还原换算假设系统顶框存在；在系统提交外框前保留真实的普通窗口尺寸。
            WindowPosition position=(WindowPosition)Marshal.PtrToStructure(message.LParam,typeof(WindowPosition));
            if((position.flags&1)==0){position.width=lastNormalBounds.Width;position.height=lastNormalBounds.Height;}
            if((position.flags&2)==0){position.x=lastNormalBounds.X;position.y=lastNormalBounds.Y;}
            Marshal.StructureToPtr(position,message.LParam,false);
        }
        if(message.Msg==0x83 && message.WParam!=IntPtr.Zero) {
            // 复用 Tao 的两种客户区计算：最大化铺满所在屏幕工作区，普通窗口保留侧/底框。
            if(IsZoomed(Handle)) {
                Rectangle area=Screen.FromHandle(Handle).WorkingArea;
                Marshal.WriteInt32(message.LParam,0,area.Left);
                Marshal.WriteInt32(message.LParam,4,area.Top);
                Marshal.WriteInt32(message.LParam,8,area.Right);
                Marshal.WriteInt32(message.LParam,12,area.Bottom);
                message.Result=IntPtr.Zero;
                return;
            }
            int top=Marshal.ReadInt32(message.LParam,4);
            base.WndProc(ref message);
            Marshal.WriteInt32(message.LParam,4,top);
            message.Result=IntPtr.Zero;
            return;
        }
        if(message.Msg==0x84) {
            if(IsZoomed(Handle)) {message.Result=new IntPtr(1);return;}
            long point=message.LParam.ToInt64();
            Point screen=new Point((short)(point&65535),(short)((point>>16)&65535));
            Rectangle outer=Bounds;
            int edge=ResizeBorderPixels();
            if(screen.Y>=outer.Top&&screen.Y<outer.Top+edge&&screen.X>=outer.Left&&screen.X<outer.Right) {
                message.Result=new IntPtr(screen.X<outer.Left+edge?13:screen.X>=outer.Right-edge?14:12);
                return;
            }
        }
        base.WndProc(ref message);
        if(message.Msg==0x5) {
            if(message.WParam.ToInt64()==2)restoreFromMaximized=true;
            else if(message.WParam==IntPtr.Zero) {
                if(restoreFromMaximized&&!restoreQueued) {
                    restoreQueued=true;
                    BeginInvoke(new Action(delegate {
                        restoreQueued=false;
                        if(!IsDisposed&&!IsZoomed(Handle))restoreFromMaximized=false;
                    }));
                } else if(!restoreFromMaximized)lastNormalBounds=Bounds;
            }
        }
        if(message.Msg==0x3&&!restoreFromMaximized&&WindowState==FormWindowState.Normal&&!IsZoomed(Handle))lastNormalBounds=Bounds;
    }
    int ResizeBorderPixels() {
        uint dpi=GetDpiForWindow(Handle);
        return GetSystemMetricsForDpi(33,dpi)+GetSystemMetricsForDpi(92,dpi);
    }
    void SynchronizeViewBounds() {
        if(view==null||view.IsDisposed||WindowState==FormWindowState.Minimized)return;
        Rectangle bounds=ClientRectangle;
        if(bounds.Width<=0||bounds.Height<=0)return;
        view.Bounds=bounds;
        view.Invalidate(true);
    }
    protected override void OnClientSizeChanged(EventArgs e) {
        base.OnClientSizeChanged(e);
        SynchronizeViewBounds();
    }
    protected override void OnResizeEnd(EventArgs e) {
        base.OnResizeEnd(e);
        SynchronizeViewBounds();
        if(view!=null&&!view.IsDisposed)view.Refresh();
    }
    public async Task Prepare(CoreWebView2Environment environment,string url) {
        Show();
        await view.EnsureCoreWebView2Async(environment);
        view.CoreWebView2.Settings.AreDevToolsEnabled=false;
        view.CoreWebView2.Settings.IsStatusBarEnabled=false;
        view.CoreWebView2.NavigationStarting += delegate(object sender,CoreWebView2NavigationStartingEventArgs e) {
            if(!Trusted(e.Uri)){e.Cancel=true;if(e.IsUserInitiated)OpenExternal(e.Uri);}
        };
        view.CoreWebView2.NewWindowRequested += delegate(object sender,CoreWebView2NewWindowRequestedEventArgs e){e.Handled=true;if(e.IsUserInitiated)OpenExternal(e.Uri);};
        view.CoreWebView2.PermissionRequested += delegate(object sender,CoreWebView2PermissionRequestedEventArgs e){e.State=CoreWebView2PermissionState.Deny;};
        view.CoreWebView2.WebMessageReceived += Receive;
        await view.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(File.ReadAllText(Path.Combine(Program.Root,"local-launcher","ui","desktop-titlebar.js")));
        view.CoreWebView2.Navigate(url);
    }
    static void OpenExternal(string value) {
        Uri uri;if(!Uri.TryCreate(value,UriKind.Absolute,out uri)||(uri.Scheme!="http"&&uri.Scheme!="https")||!String.IsNullOrEmpty(uri.UserInfo))return;
        try{Process.Start(new ProcessStartInfo(value){UseShellExecute=true});}catch(Exception){}
    }
    async void Receive(object sender,CoreWebView2WebMessageReceivedEventArgs e) {
        if(!Trusted(e.Source))return;
        string id="";
        try {
            var data=json.Deserialize<Dictionary<string,object>>(e.WebMessageAsJson);
            if(!data.ContainsKey("channel")||(string)data["channel"]!="desktop")return;
            id=data.ContainsKey("id")?Convert.ToString(data["id"]):"";
            string command=Convert.ToString(data["command"]);object result=null;
            switch(command) {
                case "window_hide": Reply(id,true,null,null);hide();return;
                case "window_minimize": WindowState=FormWindowState.Minimized;break;
                case "window_toggle_maximize": WindowState=WindowState==FormWindowState.Maximized?FormWindowState.Normal:FormWindowState.Maximized;break;
                case "window_is_maximized": result=WindowState==FormWindowState.Maximized;break;
                case "window_resize_border": result=ResizeBorderPixels()*96.0/GetDpiForWindow(Handle);break;
                case "window_start_resizing":
                    // WebView 子窗口覆盖顶部客户区，用原生命中值交回系统缩放循环。
                    if(WindowState!=FormWindowState.Normal)break;
                    Point cursor=Cursor.Position;Rectangle bounds=Bounds;int edge=ResizeBorderPixels();
                    if(cursor.Y<bounds.Top||cursor.Y>=bounds.Top+edge||cursor.X<bounds.Left||cursor.X>=bounds.Right)break;
                    int hit=cursor.X<bounds.Left+edge?13:cursor.X>=bounds.Right-edge?14:12;
                    ReleaseCapture();SendMessage(Handle,0xA1,new IntPtr(hit),IntPtr.Zero);break;
                case "window_start_dragging": ReleaseCapture();SendMessage(Handle,0xA1,new IntPtr(2),IntPtr.Zero);break;
                case "window_close": Close();break;
                case "window_exit_application": await quit();break;
                default: throw new InvalidOperationException("不支持的窗口操作。");
            }
            Reply(id,true,result,null);
        }catch(Exception error){Reply(id,false,null,error.Message);}
    }
    void Reply(string id,bool success,object result,string error) {
        if(!IsDisposed&&view.CoreWebView2!=null)view.CoreWebView2.PostWebMessageAsJson(json.Serialize(new{kind="desktop-result",id=id,success=success,result=result,error=error}));
    }
    public void BeginReveal() {preparing=false;ShowInTaskbar=true;WindowState=FormWindowState.Normal;Show();}
    public void DestroyWindow() {forceClose=true;Close();}
}
