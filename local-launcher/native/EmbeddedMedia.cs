// 发布副本专用：直接读取 EXE 资源，支持视频播放器的字节范围请求，不生成 Base64 副本。
using System;
using System.Collections.Generic;
using System.IO;
using System.Text.RegularExpressions;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

static class EmbeddedMedia {
    internal const string ResourceName="AzurPilot.Media.Background.mp4";
    internal static bool ResolveRange(string range,long length,out long start,out long end) {
        start=0;end=length-1;
        if(String.IsNullOrEmpty(range))return length>0;
        Match match=Regex.Match(range,@"^bytes=(\d*)-(\d*)$",RegexOptions.IgnoreCase);
        if(!match.Success||length<=0)return false;
        string a=match.Groups[1].Value,b=match.Groups[2].Value;
        long value;
        if(a.Length==0) {
            if(!Int64.TryParse(b,out value)||value<=0)return false;
            start=length-Math.Min(length,value);return true;
        }
        if(!Int64.TryParse(a,out start)||start<0||start>=length)return false;
        if(b.Length>0) {
            if(!Int64.TryParse(b,out value)||value<start)return false;
            end=Math.Min(end,value);
        }
        return true;
    }
    internal static void Attach(WebView2 view,CoreWebView2Environment environment,string origin) {
        var assembly=typeof(Program).Assembly;
        using(Stream resource=assembly.GetManifestResourceStream(ResourceName)) {
            if(resource==null)throw new InvalidOperationException("发布包的内嵌视频资源缺失。");
        }
        string url="https://azurpilot-media.local/background.mp4";
        var streams=new List<Stream>();
        view.Disposed+=delegate {foreach(Stream stream in streams)stream.Dispose();streams.Clear();};
        // 文件映射域名不触发 WebResourceRequested；媒体使用独立的本机拦截域名。
        view.CoreWebView2.AddWebResourceRequestedFilter("https://azurpilot-media.local/*",CoreWebView2WebResourceContext.All);
        view.CoreWebView2.WebResourceRequested+=delegate(object sender,CoreWebView2WebResourceRequestedEventArgs e) {
            if(e.Request.Uri!=url){e.Response=environment.CreateWebResourceResponse(Stream.Null,404,"Not Found","Content-Length: 0");return;}
            if(e.Request.Method!="GET"&&e.Request.Method!="HEAD") {
                e.Response=environment.CreateWebResourceResponse(Stream.Null,405,"Method Not Allowed","Allow: GET, HEAD\r\nContent-Length: 0");return;
            }
            Stream source=assembly.GetManifestResourceStream(ResourceName);
            long length=source.Length,start,end;
            string range=e.Request.Headers.Contains("Range")?e.Request.Headers.GetHeader("Range"):null;
            if(!ResolveRange(range,length,out start,out end)) {
                source.Dispose();
                e.Response=environment.CreateWebResourceResponse(Stream.Null,416,"Range Not Satisfiable","Content-Range: bytes */"+length+"\r\nContent-Length: 0");return;
            }
            bool partial=!String.IsNullOrEmpty(range);
            string headers="Content-Type: video/mp4\r\nAccept-Ranges: bytes\r\nCache-Control: no-store\r\nContent-Length: "+(end-start+1);
            if(partial)headers+="\r\nContent-Range: bytes "+start+"-"+end+"/"+length;
            Stream body=Stream.Null;
            if(e.Request.Method=="HEAD")source.Dispose();
            else {body=new MediaSlice(source,start,end-start+1);streams.Add(body);}
            e.Response=environment.CreateWebResourceResponse(body,partial?206:200,partial?"Partial Content":"OK",headers);
        };
    }
    internal sealed class MediaSlice : Stream {
        readonly Stream source;
        readonly long offset,length;
        long position;
        internal MediaSlice(Stream source,long offset,long length){this.source=source;this.offset=offset;this.length=length;}
        public override bool CanRead {get{return source.CanRead;}}
        public override bool CanSeek {get{return source.CanSeek;}}
        public override bool CanWrite {get{return false;}}
        public override long Length {get{return length;}}
        public override long Position {get{return position;}set{if(value<0||value>length)throw new ArgumentOutOfRangeException("value");position=value;}}
        public override int Read(byte[] buffer,int index,int count) {
            if(count<0||index<0||buffer==null||index>buffer.Length-count)throw new ArgumentException("读取范围无效。");
            source.Position=offset+position;
            int read=source.Read(buffer,index,(int)Math.Min(count,length-position));position+=read;return read;
        }
        public override long Seek(long value,SeekOrigin origin) {
            Position=checked((origin==SeekOrigin.Begin?0:origin==SeekOrigin.Current?position:length)+value);return position;
        }
        public override void Flush(){}
        public override void SetLength(long value){throw new NotSupportedException();}
        public override void Write(byte[] buffer,int index,int count){throw new NotSupportedException();}
        protected override void Dispose(bool disposing){if(disposing)source.Dispose();base.Dispose(disposing);}
    }
}
