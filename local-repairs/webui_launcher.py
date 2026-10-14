"""固定本地修复后启动 WebUI：慢启动不限时，明确失败不再死等。"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import webbrowser
from uuid import uuid4


class LaunchError(RuntimeError):
    """启动条件不满足或后端明确失败。"""


def shutdown_channel(root: Path):
    # 不导入 runtime 包的日志初始化：统一后端正在捕获结构化进度。
    spec = importlib.util.spec_from_file_location('launcher_shutdown_channel', root / 'module/runtime/local_webui_stop.py')
    channel = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(channel)
    return channel


def read_setting(root: Path, name: str, default: str = '') -> str:
    text = (root / 'config/deploy.yaml').read_text(encoding='utf-8-sig')
    values = re.findall(rf'^[\t ]*{re.escape(name)}:[\t ]*([^\r\n#]*)', text, re.MULTILINE)
    if len(values) > 1:
        raise LaunchError(f'部署设置 {name} 重复，无法确定启动状态。')
    return values[0].strip() if values else default


def git_revision(git: str, root: Path, reference: str, cancelled=None, timeout=120) -> str:
    """冷启动允许慢磁盘，持续报告进度并响应明确中断。"""
    process = subprocess.Popen(
        [git, '-C', str(root), 'rev-parse', reference], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
    )
    started = time.monotonic()
    next_message = started + 10
    try:
        while True:
            if cancelled is not None and cancelled():
                raise KeyboardInterrupt
            try:
                output, errors = process.communicate(timeout=.2)
                break
            except subprocess.TimeoutExpired:
                now = time.monotonic()
                if now - started >= timeout:
                    raise LaunchError('Git 版本校验持续无响应，请查看启动日志后重试。')
                if now >= next_message:
                    print('[校验] 正在读取固定版本，磁盘响应较慢；可查看启动日志或中断。', flush=True)
                    next_message = now + 10
        if process.returncode:
            raise LaunchError('Git 无法读取固定版本：' + errors.decode('utf-8', errors='replace')[-2000:])
        revision = output.decode('utf-8').strip()
        if not re.fullmatch(r'[0-9a-f]{40}', revision):
            raise LaunchError('Git 返回的固定版本号不正确。')
        return revision
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()


def verify_repair(root: Path, cancelled=None) -> dict:
    manifest_path = root / 'local-repairs/manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    if manifest.get('schema_version') != 1:
        raise LaunchError('本地修复记录格式不支持。')
    bundled_git = root / '.venv/Scripts/git/cmd/git.exe'
    git = str(bundled_git) if bundled_git.is_file() else shutil.which('git')
    if not git:
        raise LaunchError('找不到 Git，无法确认固定版本。')
    print('[校验] 正在核对本地版本与修复文件…', flush=True)
    current_revision = git_revision(git, root, 'HEAD', cancelled)
    expected_revision = manifest['revision']
    if manifest.get('revision_ref'):
        reference = manifest['revision_ref']
        if not re.fullmatch(r'refs/tags/[A-Za-z0-9._/-]+', reference):
            raise LaunchError('固定版本标签格式不正确。')
        expected_revision = git_revision(git, root, reference + '^{commit}', cancelled)
    if current_revision != expected_revision:
        raise LaunchError('程序版本已经改变，请先按新版核查并恢复修复；此次不启动。')
    for relative, expected in manifest['files'].items():
        if cancelled is not None and cancelled():
            raise KeyboardInterrupt
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()):
            raise LaunchError('本地修复记录包含安装目录之外的文件。')
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise LaunchError(f'修复文件已改变或补丁丢失：{relative}。请先恢复并验证，此次不启动。')
    if read_setting(root, 'EnableReload').lower() != 'false':
        raise LaunchError('固定修复期间必须关闭 EnableReload；此次不启动。')
    if read_setting(root, 'AutoRestartTime').lower() not in ('', 'null', '~'):
        raise LaunchError('定时更新计划尚未关闭；此次不启动。')
    if manifest.get('local_only'):
        required = {'CheckUpdateInterval': '0', 'EnableRemoteAccess': 'false',
                    'DiscordRichPresence': 'false', 'StartOcrServer': 'false',
                    'UseOcrServer': 'false', 'WebuiHost': '127.0.0.1'}
        for name, value in required.items():
            if read_setting(root, name).lower() != value:
                raise LaunchError(f'本地模式设置已改变：{name}；请先恢复本地设置。')
        if read_setting(root, 'Run').lower() not in ('', 'null', '~'):
            raise LaunchError('本地模式首次启动不能自动运行游戏任务。')
    manifest['verified_revision'] = expected_revision
    return manifest


def probe_webui(url: str) -> str:
    """只有本服务的健康检查和前端页面均正常才返回 ready。"""
    try:
        with urlopen(Request(url + '/healthz'), timeout=2) as response:
            data = json.loads(response.read(4096))
        if data.get('status') != 'ok' or data.get('protocolVersion') != 1:
            return 'foreign'
    except HTTPError as error:
        code = error.code
        error.close()
        return 'foreign' if code < 500 else 'waiting'
    except (URLError, TimeoutError, OSError):
        return 'waiting'
    except (ValueError, AttributeError):
        return 'foreign'
    try:
        with urlopen(Request(url + '/'), timeout=2) as response:
            return 'ready' if response.status == 200 else 'frontend_error'
    except HTTPError as error:
        error.close()
        return 'frontend_error'
    except (URLError, TimeoutError, OSError):
        return 'waiting'


def port_is_open(port: int) -> bool:
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.5):
            return True
    except OSError:
        return False


@contextmanager
def startup_lock(root: Path):
    """防止两个入口在后端尚未监听时同时创建进程。"""
    path = root / 'cache/local-repair-startup.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if path.stat().st_size == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if sys.platform == 'win32':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise LaunchError('已有一个启动入口正在等待，不重复创建后台进程。') from error
        try:
            yield
        finally:
            stream.seek(0)
            if sys.platform == 'win32':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def wait_for_webui(process, url: str, log_path: Path, poll_seconds: float = 2, cancelled=None) -> float:
    started = time.monotonic()
    next_message = started
    while True:
        if cancelled is not None and cancelled():
            raise KeyboardInterrupt
        code = process.poll()
        if code is not None:
            raise LaunchError(f'后端已退出（退出码 {code}），停止等待。启动日志：{log_path}')
        status = probe_webui(url)
        if status == 'ready':
            return time.monotonic() - started
        if status == 'foreign':
            raise LaunchError('端口上的服务不是预期的 WebUI，停止等待。')
        if status == 'frontend_error':
            raise LaunchError(f'后端已响应，但前端页面不可用。启动日志：{log_path}')
        now = time.monotonic()
        if now >= next_message:
            print(f'[启动] 仍在初始化，已等待 {int(now - started)} 秒；启动日志：{log_path}', flush=True)
            next_message = now + 15
        time.sleep(poll_seconds)


def stop_owned_start(process, identity, root: Path, stop_event: str):
    """只清理本次创建且身份仍匹配的启动树；不按进程名关闭其他程序。"""
    import psutil
    if process.poll() is not None:
        return
    try:
        owner = psutil.Process(process.pid)
        if abs(owner.create_time() - identity) >= .01:
            raise LaunchError('启动进程身份发生变化，拒绝中断未知进程。')
        targets = []
        for p in owner.children(recursive=True) + [owner]:
            try:
                if (Path(p.exe()).resolve().is_relative_to(root.resolve())
                        and p.environ().get('AZURPILOT_LOCAL_STOP_EVENT') == stop_event):
                    targets.append(p)
            except psutil.NoSuchProcess:
                pass
        shutdown_channel(root).signal_shutdown(stop_event)
        _, alive = psutil.wait_procs(targets, timeout=5)
        for p in alive:
            p.terminate()
        _, alive = psutil.wait_procs(alive, timeout=5)
        for p in alive:
            p.kill()
        psutil.wait_procs(alive, timeout=5)
    except psutil.NoSuchProcess:
        pass
    process.wait(timeout=15)


def launch(root: Path, open_browser: bool = True, cancelled=None, on_created=None) -> int:
    if cancelled is not None and cancelled():
        raise KeyboardInterrupt
    manifest = verify_repair(root, cancelled)
    port = int(read_setting(root, 'WebuiPort', '25548'))
    if not 1 <= port <= 65535:
        raise LaunchError('WebuiPort 超出有效范围。')
    url = f'http://127.0.0.1:{port}'
    python = root / '.venv/Scripts/python.exe'
    if not python.is_file() or not (root / 'gui.py').is_file():
        raise LaunchError('现有 Python 环境或 gui.py 缺失，不会自动删除或重建环境。')
    with startup_lock(root):
        if cancelled is not None and cancelled():
            raise KeyboardInterrupt
        if probe_webui(url) == 'ready':
            print(f'[启动] 已有 WebUI 可用，复用现有服务：{url}', flush=True)
            print('[启动] 如刚修改源码，请先退出已有 WebUI，再重新启动以加载修复。', flush=True)
            if open_browser:
                webbrowser.open(url)
            return 0
        if port_is_open(port):
            raise LaunchError('端口已占用但 WebUI 尚未就绪，请检查已有服务；不重复启动。')
        log_path = root / 'log' / ('local-launch-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.txt')
        log_path.parent.mkdir(parents=True, exist_ok=True)
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        stop_event = 'Local\\AzurPilot-WebUI-' + uuid4().hex
        # 预先持有事件，初始化尚未开始时也能收到本次启动的取消通知。
        event_kernel = event_handle = None
        if sys.platform == 'win32':
            event_kernel = shutdown_channel(root).windows_events()
            event_handle = event_kernel.CreateEventW(None, False, False, stop_event)
            if not event_handle:
                raise LaunchError('无法创建本次启动的关闭通道。')
        environment = dict(os.environ, AZURPILOT_LOCAL_STOP_EVENT=stop_event)
        if manifest.get('local_only'):
            guard = root / 'local-maintenance/offline-runtime'
            if not (guard / 'sitecustomize.py').is_file():
                raise LaunchError('本地网络限制组件缺失。')
            environment['AZURPILOT_LOCAL_MODE'] = '1'
            environment['PYTHONPATH'] = str(guard) + os.pathsep + str(root)
            for key in list(environment):
                if key.upper() in {'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY'}:
                    environment.pop(key)
            environment['NO_PROXY'] = 'localhost,127.0.0.1,::1'
        try:
            with log_path.open('wb') as output:
                process = subprocess.Popen(
                    [str(python), '-X', 'utf8', 'gui.py'], cwd=root,
                    stdout=output, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=flags, env=environment,
                )
        except BaseException:
            if event_handle:
                event_kernel.CloseHandle(event_handle)
            raise
        import psutil
        identity = psutil.Process(process.pid).create_time()
        verified_revision = manifest.get('verified_revision', manifest['revision'])
        print(f'[启动] 固定版本 {verified_revision[:9]}，修复完整；开始启动 WebUI。', flush=True)
        try:
            if on_created is not None:
                on_created(process, identity, stop_event)
            elapsed = wait_for_webui(process, url, log_path, cancelled=cancelled)
            if cancelled is not None and cancelled():
                raise KeyboardInterrupt
        except BaseException:
            stop_owned_start(process, identity, root, stop_event)
            raise
        finally:
            if event_handle:
                event_kernel.CloseHandle(event_handle)
        receipt = dict(revision=verified_revision, pid=process.pid, url=url,
                       created_at=psutil.Process(process.pid).create_time(), stop_event=stop_event,
                       elapsed_seconds=round(elapsed, 2), log=str(log_path))
        (root / 'cache/local-repair-startup.json').write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8',
        )
        print(f'[启动] WebUI 已就绪，用时 {elapsed:.1f} 秒：{url}', flush=True)
        if open_browser:
            webbrowser.open(url)
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description='保留本地修复的 WebUI 启动入口')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        if args.check:
            verify_repair(args.root)
            print('[启动检查] 固定版本、修复文件及更新设置均通过。', flush=True)
            return 0
        return launch(args.root, open_browser=not args.no_browser)
    except (LaunchError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f'[启动失败] {error}', file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        print('[启动] 已取消等待。', flush=True)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
