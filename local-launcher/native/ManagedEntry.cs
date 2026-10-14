// 固定 EXE 负责选择已验收版本；后台更新只原子切换目录记录。
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;

static class ManagedEntry {
    internal static string Resolve(string installation) {
        string pointer=Path.Combine(installation,".updates","current.json");
        if(!File.Exists(pointer))return installation;
        string text;
        using(var stream=new FileStream(pointer,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete))
        using(var reader=new StreamReader(stream,Encoding.UTF8))text=reader.ReadToEnd();
        var record=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(text);
        if(record==null||!record.ContainsKey("schema_version")||Convert.ToInt32(record["schema_version"])!=1||!record.ContainsKey("active"))throw new InvalidDataException("当前版本记录格式错误。");
        string relative=record["active"] as string;
        if(relative==".")return installation;
        if(relative==null||!Regex.IsMatch(relative,@"\Aversions/[A-Za-z0-9][A-Za-z0-9._-]{0,119}\z"))throw new InvalidDataException("当前版本目录不正确。");
        string target=Path.GetFullPath(Path.Combine(installation,relative.Replace('/',Path.DirectorySeparatorChar)));
        string versions=Path.Combine(installation,"versions");
        if(Directory.Exists(versions)&&(File.GetAttributes(versions)&FileAttributes.ReparsePoint)!=0)throw new InvalidDataException("版本目录不能使用外部链接。");
        if(!target.StartsWith(installation+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)||!Directory.Exists(target)||(File.GetAttributes(target)&FileAttributes.ReparsePoint)!=0)throw new InvalidDataException("当前版本目录缺失或无效。");
        if(!File.Exists(Path.Combine(target,"local-repairs","manifest.json")))throw new InvalidDataException("当前版本没有完成安装。");
        return target;
    }
    internal static bool RelaunchHelper(string[] args,string entry) {
        if(args.Length==0||args[0]!="--relaunch-after")return false;
        int pid;long ticks;
        if(args.Length!=3||!Int32.TryParse(args[1],out pid)||!Int64.TryParse(args[2],out ticks))return true;
        try{using(Process parent=Process.GetProcessById(pid)){if(parent.StartTime.ToUniversalTime().Ticks!=ticks)return true;if(!parent.WaitForExit(120000))return true;}}
        catch(ArgumentException){}
        Process.Start(new ProcessStartInfo(entry){UseShellExecute=false,WorkingDirectory=Path.GetDirectoryName(entry)});
        return true;
    }
    internal static void RestartAfterExit(string entry) {
        using(Process current=Process.GetCurrentProcess()) {
            string arguments="--relaunch-after "+current.Id.ToString(CultureInfo.InvariantCulture)+" "+current.StartTime.ToUniversalTime().Ticks.ToString(CultureInfo.InvariantCulture);
            Process.Start(new ProcessStartInfo(entry,arguments){UseShellExecute=false,CreateNoWindow=true,WorkingDirectory=Path.GetDirectoryName(entry)});
        }
    }
}
