// 启动诊断独立于服务：服务尚未就绪时也能读取与保存现场。
using System;using System.Collections.Generic;using System.IO;using System.Text;using System.Text.RegularExpressions;

sealed class LauncherDiagnostics {
    readonly string root;
    readonly StringBuilder activity=new StringBuilder();
    readonly HashSet<string> paths=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    readonly object gate=new object();
    DateTime since=DateTime.Now;
    internal LauncherDiagnostics(string directory){
        root=Path.GetFullPath(directory);
        string jobs=Path.Combine(root,"cache","local-launcher","jobs");
        if(Directory.Exists(jobs)){
            var files=new List<string>(Directory.GetFiles(jobs,"*.jsonl"));files.Sort((a,b)=>File.GetLastWriteTimeUtc(b).CompareTo(File.GetLastWriteTimeUtc(a)));
            foreach(string file in files){
                try{using(var stream=new FileStream(file,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete))using(var reader=new StreamReader(stream,Encoding.UTF8)){
                    if(Regex.IsMatch(reader.ReadLine()??"",@"""action""\s*:\s*""start""")){Track(file);since=File.GetLastWriteTime(file);break;}
                }}catch(IOException){}
            }
        }
    }
    internal void Begin(string action,string mode){lock(gate){activity.Clear();paths.Clear();since=DateTime.Now;Append("操作："+action+"；启动方式："+mode);}}
    internal void Append(string value){lock(gate){activity.AppendLine(DateTime.Now.ToString("HH:mm:ss.fff")+" "+value);if(activity.Length>256000)activity.Remove(0,activity.Length-256000);}}
    internal void Track(string value){
        if(String.IsNullOrEmpty(value))return;
        try{
            string full=Path.GetFullPath(value),logs=Path.Combine(root,"log")+Path.DirectorySeparatorChar,jobs=Path.Combine(root,"cache","local-launcher","jobs")+Path.DirectorySeparatorChar;
            if((full.StartsWith(logs,StringComparison.OrdinalIgnoreCase)||full.StartsWith(jobs,StringComparison.OrdinalIgnoreCase))&&(full.EndsWith(".txt",StringComparison.OrdinalIgnoreCase)||full.EndsWith(".jsonl",StringComparison.OrdinalIgnoreCase)))lock(gate)paths.Add(full);
        }catch(ArgumentException){}catch(NotSupportedException){}
    }
    static string Tail(string path){
        try{using(var stream=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete)){
            if(stream.Length>65536)stream.Seek(-65536,SeekOrigin.End);
            using(var reader=new StreamReader(stream,Encoding.UTF8))return reader.ReadToEnd();
        }}catch(IOException error){return "日志暂不可读："+error.Message;}catch(UnauthorizedAccessException error){return "日志暂不可读："+error.Message;}
    }
    HashSet<string> Gather(out string text){
        var found=new HashSet<string>(StringComparer.OrdinalIgnoreCase);DateTime started;
        lock(gate){foreach(string p in paths)found.Add(p);text=activity.ToString();started=since;}
        string logs=Path.Combine(root,"log");
        if(Directory.Exists(logs)){
            var launches=new List<string>(Directory.GetFiles(logs,"local-launch-*.txt"));launches.Sort((a,b)=>File.GetLastWriteTimeUtc(b).CompareTo(File.GetLastWriteTimeUtc(a)));
            if(launches.Count>0)found.Add(launches[0]);
            foreach(string day in new[]{started.ToString("yyyy-MM-dd"),DateTime.Now.ToString("yyyy-MM-dd")})foreach(string suffix in new[]{"_gui-launcher.txt","_webui.txt"}){
                string file=Path.Combine(logs,day+suffix);if(File.Exists(file))found.Add(file);
            }
        }
        return found;
    }
    internal string Read(){
        string text;var found=Gather(out text);if(text.Length>50000)text=text.Substring(text.Length-50000);
        var output=new StringBuilder("AzurPilot 启动诊断\r\n生成时间："+DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss")+"\r\n\r\n");output.AppendLine(text);
        foreach(string file in found){output.AppendLine("\r\n===== "+file.Substring(root.Length).TrimStart(Path.DirectorySeparatorChar)+" =====");output.AppendLine(Tail(file));if(output.Length>280000)break;}
        if(found.Count==0&&text.Length==0)output.AppendLine("当前还没有启动记录。");
        return output.ToString();
    }
    internal void Save(string destination){
        string text;var found=Gather(out text);
        if(found.Contains(Path.GetFullPath(destination)))throw new IOException("请选择新的导出文件，避免覆盖运行日志。");
        using(var writer=new StreamWriter(destination,false,new UTF8Encoding(true))){
            writer.WriteLine("AzurPilot 启动诊断\r\n生成时间："+DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"));writer.WriteLine(text);
            char[] buffer=new char[8192];
            foreach(string file in found){
                writer.WriteLine("\r\n===== "+file.Substring(root.Length).TrimStart(Path.DirectorySeparatorChar)+" =====");
                try{using(var stream=new FileStream(file,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete))using(var reader=new StreamReader(stream,Encoding.UTF8)){
                    int count;while((count=reader.Read(buffer,0,buffer.Length))>0)writer.Write(buffer,0,count);
                }}catch(IOException error){writer.WriteLine("日志暂不可读："+error.Message);}catch(UnauthorizedAccessException error){writer.WriteLine("日志暂不可读："+error.Message);}
            }
        }
    }
}
