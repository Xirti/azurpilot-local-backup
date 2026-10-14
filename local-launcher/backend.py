"""统一启动器的后端：固定操作、结构化进度、独立候选更新。

直接调用已验证的本地维护入口，不启动账号任务，不执行任意前端命令。
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stdout
from datetime import datetime
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import threading
import traceback
import uuid

ROOT = Path(__file__).resolve().parents[1]
ACTIONS = ('inspect', 'start', 'stop', 'initialize', 'check', 'backup',
           'restore', 'prepare-candidate', 'patch', 'rebuild-frontend', 'rebuild-runtime',
           'check-update', 'update', 'rollback')
FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
MAX_JOB_FILES = 20


def module_from_file(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Events:
    """JSON 行协议与有上限的本机日志；不能把日志输出当作成功信号。"""
    def __init__(self, root: Path, action: str):
        self.action = action
        self.id = uuid.uuid4().hex
        self.started = time.monotonic()
        self.path = root / 'cache/local-launcher/jobs' / (self.id + '.jsonl')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        old = sorted(self.path.parent.glob('*.jsonl'), key=lambda p: p.stat().st_mtime, reverse=True)
        # 只删除自己的历史 job 文件，不碰任务日志、截图或私人配置。
        for p in old[MAX_JOB_FILES - 1:]:
            try:
                p.unlink()
                p.with_suffix('.command.txt').unlink(missing_ok=True)
                p.with_suffix('.error.txt').unlink(missing_ok=True)
            except OSError:
                pass
        self.stream = self.path.open('w', encoding='utf-8')
        self.output = sys.stdout
        self.cancelled = threading.Event()
        self.handoff = threading.Event()
        self.detached = threading.Event()
        self.wait_handoff = False

    def emit(self, phase: str, status: str, message: str, result=None):
        record = {'protocol': 1, 'job': self.id, 'action': self.action,
                  'phase': phase, 'status': status, 'message': message,
                  'elapsed_seconds': round(time.monotonic() - self.started, 1),
                  'log_path': str(self.path)}
        if result is not None:
            record['result'] = result
        text = json.dumps(record, ensure_ascii=False)
        if self.output is not None:
            try:
                self.output.write(text + '\n')
                self.output.flush()
            except (BrokenPipeError, OSError):
                # 启动器窗口先退出时继续完成作业，不能连带取消已创建的 WebUI。
                self.output = None
        # 单份日志也设上限，长时间启动等待不无限写入。
        if self.stream.tell() < 2 * 1024 * 1024:
            self.stream.write(text + '\n')
            self.stream.flush()

    def close(self):
        self.stream.close()


class ProgressOutput(io.TextIOBase):
    """将已有入口的进度转为 JSON 行；只保留短消息，不保存完整运行日志副本。"""
    def __init__(self, events: Events):
        self.events = events
        self.pending = ''

    def write(self, text):
        self.pending += text
        while '\n' in self.pending:
            line, self.pending = self.pending.split('\n', 1)
            if line.strip():
                self.events.emit('running', 'running', line.strip()[:1200])
        # 不完整超长行不能导致无限缓存。
        self.pending = self.pending[-4096:]
        return len(text)

    def flush(self):
        pass


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def git_executable(root: Path) -> str:
    bundled = root / '.venv/Scripts/git/cmd/git.exe'
    value = str(bundled) if bundled.is_file() else shutil.which('git')
    if not value:
        raise RuntimeError('Git 缺失，请先准备完整离线包。')
    return value


def run_command(arguments: list[str], root: Path, events: Events, timeout=900):
    """固定参数数组，输出直接写作业日志，禁止 shell 字符串拼接。"""
    log = events.path.with_suffix('.command.txt')
    with log.open('ab') as output:
        process = subprocess.Popen(arguments, cwd=root, stdout=output, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, creationflags=FLAGS)
        started = last = time.monotonic()
        while process.poll() is None:
            now = time.monotonic()
            if now - started > timeout:
                process.terminate()
                process.wait(timeout=20)
                raise RuntimeError(f'准备命令超时，已停止本次命令。日志：{log}')
            if now - last > 15:
                events.emit('preparing', 'running', f'准备中，命令日志：{log}')
                last = now
            time.sleep(.2)
    if log.stat().st_size > 2 * 1024 * 1024:
        with log.open('rb') as source:
            source.seek(-2 * 1024 * 1024, os.SEEK_END)
            tail = source.read()
        log.write_bytes(tail)
    if process.returncode:
        raise RuntimeError(f'准备命令失败（{process.returncode}），请查看 {log}')
    return str(log)


def candidate_path(root: Path, value: str) -> Path:
    """明确新建独立目录；拒绝稳定安装、其子目录和父目录。"""
    if not value.strip():
        raise ValueError('请选择独立候选目录。')
    candidate = Path(value).expanduser().resolve()
    if candidate == root or candidate.is_relative_to(root) or root.is_relative_to(candidate):
        raise ValueError('候选目录不能与当前安装相同，也不能互相包含。')
    if candidate.exists() and (not candidate.is_dir() or any(candidate.iterdir())):
        raise ValueError('候选目录必须不存在或为空；不会覆盖已有安装。')
    return candidate


def validate_candidate(root: Path, candidate: Path):
    candidate = candidate.resolve()
    if candidate == root or candidate.is_relative_to(root) or root.is_relative_to(candidate):
        raise ValueError('请选择独立候选安装，不能修改当前稳定目录。')
    if not (candidate / 'local-maintenance/candidate.json').is_file():
        raise ValueError('目录没有本启动器的候选记录，请先准备候选版。')
    return candidate


def prepare_candidate(root: Path, destination: str, reference: str, events: Events) -> dict:
    """获取用户选定官方版本，复制必要工具；直到迁移/验收完成前禁止自动启动。"""
    candidate = candidate_path(root, destination)
    if reference and (reference.startswith('-') or not re.fullmatch(r'[A-Za-z0-9._/+-]{1,200}', reference)):
        raise ValueError('版本只能填写分支、标签或提交号。')
    provenance = read_json(root / 'local-maintenance/provenance.json')
    source = 'https://github.com/wess09/AzurPilot.git'
    # 来源固定为已核实的官方仓库，不允许前端提供任意代码来源。
    if source != 'https://github.com/wess09/AzurPilot.git':
        raise ValueError('官方来源记录已改变，需先核实来源。')
    maintain = module_from_file('launcher_maintain', root / 'local-maintenance/maintain.py')
    maintain.assert_stopped(root)
    backup = str(maintain.backup(root))
    events.emit('backup', 'running', '已备份本机配置', {'private_backup': backup})
    git = git_executable(root)
    candidate.parent.mkdir(parents=True, exist_ok=True)
    # 失败的候选目录保留，便于检查；绝不删除、清理稳定安装。
    run_command([git, 'clone', '--no-checkout', '--', source, str(candidate)], root, events)
    run_command([git, '-C', str(candidate), 'config', '--local', 'core.autocrlf', 'false'], root, events)
    if reference:
        run_command([git, '-C', str(candidate), 'fetch', 'origin', reference], root, events)
    revision = 'FETCH_HEAD' if reference else 'origin/HEAD'
    run_command([git, '-C', str(candidate), 'checkout', '--detach', revision], root, events)
    for directory in ('local-maintenance', 'local-repairs', 'local-launcher'):
        if directory == 'local-launcher' and not (root / directory).is_dir():
            continue
        shutil.copytree(root / directory, candidate / directory, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'private',
                                                     'offline-artifacts', 'runtime.json', 'settings.json', '*.mp4'))
    local_exe = root / 'AzurPilot-Local.exe'
    if local_exe.is_file():
        shutil.copy2(local_exe, candidate / local_exe.name)
    # 只复制用户本机的配置备份，不从源码仓库寻找私有账号配置。
    shutil.copytree(Path(backup) / 'config', candidate / 'config', dirs_exist_ok=True)
    record = {'schema_version': 1, 'created': datetime.now().isoformat(),
              'source': source, 'reference': reference or 'remote-default',
              'stable_root': str(root), 'private_backup': backup,
              'state': 'needs_review', 'pending': ['运行环境准备', '新版配置迁移',
                                                 '本地补丁核对', '前端构建', '新版本验收']}
    (candidate / 'local-maintenance/candidate.json').write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    # 原更新器可选存放，不自动执行其部署和启动流程。
    original = root.with_name('AzurPilot') / 'alas-launcher.exe'
    if original.is_file():
        shutil.copy2(original, candidate / 'alas-launcher-original.exe')
    return {'candidate': str(candidate), 'state': 'needs_review',
            'private_backup': backup, 'pending': record['pending'], 'game_started': False}


def repair_runtime_path(root: Path, events: Events) -> None:
    from runtime_layout import base_python
    base = base_python(root)
    cfg = root / '.venv/pyvenv.cfg'
    if not base.is_file() or not cfg.is_file():
        raise RuntimeError('完整离线运行环境缺失，请使用离线 ZIP，不是源码 ZIP。')
    text = cfg.read_text(encoding='utf-8-sig')
    if len(re.findall(r'(?m)^home\s*=.*$', text)) != 1:
        raise ValueError('pyvenv.cfg 格式不正确，未修改。')
    fixed = re.sub(r'(?m)^home\s*=.*$', lambda _: 'home = ' + str(base.parent), text)
    if fixed != text:
        temporary = cfg.with_suffix('.launcher.tmp')
        temporary.write_text(fixed, encoding='utf-8')
        temporary.replace(cfg)
        events.emit('initialize', 'running', '运行环境路径已核对')


def initialize(root: Path, events: Events) -> dict:
    maintain = module_from_file('launcher_maintain', root / 'local-maintenance/maintain.py')
    maintain.assert_stopped(root)
    repair_runtime_path(root, events)
    initializer = module_from_file('launcher_initializer', root / 'local-maintenance/initialize_release.py')
    # initialize_release 从自身所在目录导入 maintain，避免绑定到其他安装。
    sys.path.insert(0, str(root / 'local-maintenance'))
    return initializer.initialize(root, cancelled=events.cancelled.is_set)


def operate(root: Path, action: str, config: str, candidate: str, reference: str, events: Events) -> dict:
    if action == 'inspect':
        from managed_installation import Installation
        from maintain import instance_names
        installation = Installation(Path(os.environ.get('AZURPILOT_INSTALL_ROOT', root)))
        manifest = read_json(root / 'local-repairs/manifest.json')
        return {'root': str(root), 'version': manifest.get('revision_ref', manifest['revision']).removeprefix('refs/tags/'),
                'configs': instance_names(root),
                'actions': list(ACTIONS), 'updater': installation.describe()}
    launcher = module_from_file('launcher_local_start', root / 'local-repairs/webui_launcher.py')
    if action in ('check-update', 'update', 'rollback'):
        from managed_installation import for_active
        import upstream_update
        installation = for_active(root)
        if action == 'check-update':
            return upstream_update.check(root, installation, events)
        with launcher.startup_lock(root):
            if action == 'update':
                if not all((root / name).is_file() for name in ('config/deploy.yaml', '.git/index')):
                    initialize(root, events)
                return upstream_update.update(root, installation, events)
            return upstream_update.rollback(root, installation, events)
    if action == 'start':
        from managed_installation import for_active
        for_active(root)
        # 首次解压只需点击启动；暖启动/移动目录仅修正 Python 路径，不重写任务偏好。
        with launcher.startup_lock(root):
            if events.cancelled.is_set():
                raise KeyboardInterrupt
            if not all((root / name).is_file() for name in ('config/deploy.yaml', '.git/index')):
                events.emit('initialize', 'running', '首次准备本地环境')
                initialize(root, events)
            else:
                repair_runtime_path(root, events)
            if events.cancelled.is_set():
                raise KeyboardInterrupt
        # 现有入口持有启动锁，并复用已有服务；后端直接写文件，不依赖 GUI 窗口存活。
        owned = {}
        def created(process, identity, stop_event):
            owned.update(process=process, identity=identity, stop_event=stop_event)
        launcher.launch(root, open_browser=False, cancelled=events.cancelled.is_set, on_created=created)
        port = int(launcher.read_setting(root, 'WebuiPort'))
        result = {'url': f'http://127.0.0.1:{port}', 'game_started': False, 'service_created': bool(owned)}
        if events.wait_handoff:
            events.emit('ready', 'running', 'WebUI 已就绪，正在加载后续页面', result)
            while not events.handoff.is_set() and not events.detached.is_set():
                if events.cancelled.wait(.1):
                    if owned:
                        launcher.stop_owned_start(owned['process'], owned['identity'], root, owned['stop_event'])
                    raise KeyboardInterrupt
            if events.cancelled.is_set():
                if owned:
                    launcher.stop_owned_start(owned['process'], owned['identity'], root, owned['stop_event'])
                raise KeyboardInterrupt
        return result
    if action == 'stop':
        stop = module_from_file('launcher_local_stop', root / 'local-repairs/webui_stop.py')
        with launcher.startup_lock(root):
            stop.stop(root)
        return {'stopped': True, 'game_and_emulator_preserved': True}
    maintain = module_from_file('launcher_maintain', root / 'local-maintenance/maintain.py')
    config = config or next(iter(maintain.instance_names(root)), '')
    if action == 'check':
        result = maintain.audit(root, config)
        try:
            launcher.verify_repair(root)
            result['version_verified'] = True
        except launcher.LaunchError as error:
            result['version_verified'] = False
            result['version_error'] = str(error)
        result['state'] = ('succeeded' if result['version_verified'] and result['configuration_matches']
                           and all(result['repair_hashes'].values()) else 'needs_review')
        return result
    with launcher.startup_lock(root):
        if action == 'initialize':
            return initialize(root, events)
        if action == 'backup':
            from managed_installation import for_active
            from updater_build import backup_data
            from updater_sources import Commands
            installation = for_active(root)
            with installation.locked():
                destination = installation.state / 'backups' / ('manual-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
                backup_data(root, destination, Commands(events, events.path.with_suffix('.command.txt')))
                return {'private_backup': str(destination)}
        if action == 'restore':
            return maintain.restore(root, config, pause_monthly=True)
        if action == 'prepare-candidate':
            return prepare_candidate(root, candidate, reference, events)
        if action == 'patch':
            destination = validate_candidate(root, Path(candidate))
            maintain.assert_stopped(destination)
            # 使用稳定版随包 Git；候选补丁必须自己持有该目录启动锁。
            os.environ['PATH'] = str(Path(git_executable(root)).parent) + os.pathsep + os.environ.get('PATH', '')
            with launcher.startup_lock(destination):
                result = maintain.apply_source(destination)
            result['state'] = 'needs_review'
            result['pending'] = ['配置迁移', '产物重建', '新版本验收']
            return result
        if action in ('rebuild-frontend', 'rebuild-runtime'):
            destination = validate_candidate(root, Path(candidate))
            maintain.assert_stopped(destination)
            script = 'rebuild_frontend.ps1' if action == 'rebuild-frontend' else 'rebuild_runtime.ps1'
            with launcher.startup_lock(destination):
                log = run_command(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                   '-File', str(destination / 'local-maintenance/scripts' / script)], destination, events)
            return {'state': 'needs_review', 'command_log': log, 'pending': ['新版本验收']}
    raise ValueError('不支持的操作。')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=ACTIONS)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--config', default='')
    parser.add_argument('--candidate', default='')
    parser.add_argument('--reference', default='')
    parser.add_argument('--wait-handoff', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve()
    if args.config and (len(args.config) > 64 or args.config in {'.', '..'} or re.search(r'[<>:"/\\|?*\x00-\x1f]', args.config)):
        parser.error('实例名不能包含路径分隔符或 Windows 保留字符。')
    # 基础 Python 启动此入口时复用随包依赖，支持移动目录后初始化前的情况。
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / '.venv/Lib/site-packages'))
    sys.path.insert(0, str(root / 'local-maintenance'))
    events = Events(root, args.action)
    events.wait_handoff = args.wait_handoff
    if args.action in ('start', 'update', 'rollback'):
        def read_cancel():
            # 窗口普通关闭产生 EOF 时继续；只有明确的 cancel 消息才取消。
            # 不持有 sys.stdin 缓冲锁，否则 Windows 子进程继承句柄会被拖住。
            pending = b''
            try:
                while True:
                    data = os.read(0, 256)
                    if not data:
                        events.detached.set()
                        return
                    pending += data
                    while b'\n' in pending:
                        line, pending = pending.split(b'\n', 1)
                        if line.strip() == b'cancel':
                            events.cancelled.set()
                            return
                        if line.strip() == b'handoff':
                            events.handoff.set()
                            return
                    pending = pending[-256:]
            except OSError:
                events.detached.set()
                return
        threading.Thread(target=read_cancel, name='launcher-cancel', daemon=True).start()
    try:
        events.emit('begin', 'running', '正在执行：' + args.action)
        with redirect_stdout(ProgressOutput(events)):
            result = operate(root, args.action, args.config, args.candidate, args.reference, events)
        status = result.get('state', 'succeeded')
        events.emit('complete', status, '需核对后继续' if status == 'needs_review' else '操作完成', result)
        return 0 if status == 'succeeded' else 2
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        events.emit('failed', 'failed', str(error))
        return 1
    except KeyboardInterrupt:
        events.emit('cancelled', 'cancelled', '本次启动已中断')
        return 130
    except Exception as error:
        diagnostic = events.path.with_suffix('.error.txt')
        diagnostic.write_text(traceback.format_exc()[-65536:], encoding='utf-8')
        events.emit('failed', 'failed', f'{type(error).__name__}：{error}。详细错误：{diagnostic}')
        return 1
    finally:
        events.close()


if __name__ == '__main__':
    raise SystemExit(main())
