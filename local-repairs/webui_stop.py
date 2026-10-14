"""核对本安装目录的服务身份后，请求正常关闭 WebUI。"""

import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time

import psutil

ROOT = Path(__file__).resolve().parents[1]
# 独立关闭工具只加载无副作用的通道文件，避免初始化日志器并显示“启动”横幅。
spec = importlib.util.spec_from_file_location('local_stop_channel', ROOT / 'module/runtime/local_webui_stop.py')
channel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(channel)
EVENT_ENV, signal_shutdown = channel.EVENT_ENV, channel.signal_shutdown
sys.path.insert(0, str(Path(__file__).resolve().parent))
from webui_launcher import startup_lock


class StopError(RuntimeError):
    """运行身份不符或正常退出未完成。"""


def same_process(pid: int, created_at: float):
    """PID 与创建时间都匹配才承认是本次启动的进程。"""
    try:
        process = psutil.Process(pid)
        if abs(process.create_time() - created_at) >= 0.01:
            raise StopError(f'进程编号 {pid} 已被复用，不操作这个进程。')
        return process if process.is_running() else None
    except psutil.NoSuchProcess:
        return None


def service_in_root(process, root: Path, require_cwd: bool = True) -> bool:
    arguments = process.cmdline()
    return (Path(process.exe()).resolve().is_relative_to(root.resolve())
            and (not require_cwd or Path(process.cwd()).resolve() == root.resolve())
            and any(Path(argument).name.lower() == 'gui.py' for argument in arguments))


def stop(root: Path, timeout: float = 45, check_only: bool = False) -> int:
    record_path = root / 'cache/local-repair-startup.json'
    registry_path = root / 'cache/webui-workers.json'
    if not registry_path.is_file():
        print('[关闭] 没有运行中的 WebUI 登记。', flush=True)
        return 0
    registry = json.loads(registry_path.read_text(encoding='utf-8-sig'))
    owner = registry.get('owner_pid')
    if not owner:
        print('[关闭] WebUI 已关闭。', flush=True)
        return 0
    created = registry.get('owner_created_at')
    if created is None:
        raise StopError('后台登记缺少创建时间，无法安全确定关闭对象。')
    service = same_process(int(owner), float(created))
    if service is None:
        if registry.get('workers'):
            raise StopError('WebUI 已退出，但还存在任务登记；请先检查残留任务。')
        print('[关闭] WebUI 已关闭，无需重复操作。', flush=True)
        return 0
    if not record_path.is_file():
        raise StopError('服务不是由固定入口登记的，请使用其原有退出方式。')
    receipt = json.loads(record_path.read_text(encoding='utf-8-sig'))
    event = receipt.get('stop_event', '')
    if not service_in_root(service, root) or not event or service.environ().get(EVENT_ENV) != event:
        raise StopError('服务身份或本地关闭通道不匹配，不关闭未知进程。')
    launcher = same_process(int(receipt['pid']), float(receipt['created_at']))
    if launcher is not None:
        # Windows 的虚拟环境入口转交后可能停留在 Temp，实际服务的目录仍需严格匹配。
        if (not service_in_root(launcher, root, require_cwd=False)
                or (launcher.pid != service.pid and launcher.pid not in [p.pid for p in service.parents()])):
            raise StopError('启动进程身份不匹配，不关闭未知进程。')
    print(f'[关闭] 已确认本安装目录的 WebUI，运行任务数：{len(registry.get("workers", {}))}。', flush=True)
    if check_only:
        print('[关闭检查] 身份核验通过，未执行关闭。', flush=True)
        return 0
    signal_shutdown(event)
    print('[关闭] 已请求正常退出，正在停止任务和辅助后台……', flush=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining_service = same_process(int(owner), float(created))
        remaining_launcher = same_process(int(receipt['pid']), float(receipt['created_at']))
        if remaining_service is None and remaining_launcher is None:
            final = json.loads(registry_path.read_text(encoding='utf-8-sig'))
            if final.get('workers'):
                raise StopError('服务已退出，但还有任务登记；未确认完全关闭。')
            print('[关闭] WebUI 和 AzurPilot 后台已关闭；浏览器、MuMu 保留。', flush=True)
            return 0
        time.sleep(0.5)
    raise StopError('正常退出尚未完成；请查看 WebUI 日志。没有强杀其他进程。')


def main() -> int:
    parser = argparse.ArgumentParser(description='正常关闭本机固定入口启动的 WebUI')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        # 启动与关闭共用锁，关闭进行中不能另建一套后台。
        with startup_lock(args.root):
            return stop(args.root, check_only=args.check)
    except (StopError, OSError, ValueError, KeyError, RuntimeError, psutil.Error) as error:
        print(f'[关闭失败] {error}', file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
