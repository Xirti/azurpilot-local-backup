"""受控上游快照、源码筛选和本地修改的三方合并。"""
from __future__ import annotations

import fnmatch
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import time

from managed_installation import UPSTREAM_URL, atomic_json, digest

SOURCE_DIRS = {'assets', 'bin', 'campaign', 'config', 'deploy', 'frontend', 'licenses',
               'module', 'submodule', 'local-launcher', 'local-maintenance', 'local-repairs'}
ROOT_FILES = {'.gitattributes', '.gitignore', 'LICENSE', 'README.md', 'alas.py', 'gui.py',
              'tui.py', 'mcp_server_sse.py', 'pyproject.toml', 'uv.lock', 'AzurPilot-Local.exe'}
EXCLUDED = {'test', 'tests', '__tests__', 'mock', 'e2e', 'fixtures', '__pycache__',
            '.pytest_cache', 'node_modules', 'offline-artifacts', 'private'}
PATTERNS = ('test_*.py', '*_test.py', 'conftest.py', '*.test.*', '*.spec.*', '*.pyc', '*.pyo', '*.bak')
TEXT_EXTENSIONS = {'.py', '.json', '.yaml', '.yml', '.toml', '.lock', '.js', '.jsx', '.ts',
                   '.tsx', '.css', '.html', '.svg', '.md', '.txt', '.sql', '.ps1'}


def normalized_bytes(path: Path) -> bytes | None:
    if path.suffix.lower() not in TEXT_EXTENSIONS and path.name not in {'.gitignore', '.gitattributes', 'template'}:
        return None
    data = path.read_bytes()
    return None if b'\0' in data else data.replace(b'\r\n', b'\n')


def content_digest(path: Path) -> str:
    data = normalized_bytes(path)
    return digest(path) if data is None else hashlib.sha256(data).hexdigest()


def source_allowed(name: str) -> bool:
    path = Path(name)
    parts = path.parts
    if not parts or path.is_absolute() or '..' in parts:
        return False
    if any(part.lower() in EXCLUDED for part in parts) or any(fnmatch.fnmatchcase(path.name, p) for p in PATTERNS):
        return False
    if len(parts) == 1:
        return name in ROOT_FILES
    if parts[0] not in SOURCE_DIRS:
        return False
    if name.startswith(('local-launcher/data/', 'local-launcher/logs/', 'local-launcher/cache/')):
        return False
    if name in ('local-maintenance/candidate.json', 'local-maintenance/validation-private.json'):
        return False
    if parts[0] == 'config':
        return len(parts) == 2 and (fnmatch.fnmatchcase(path.name, 'template*.json')
                                   or fnmatch.fnmatchcase(path.name, 'deploy.template*.yaml')
                                   or path.name == 'webui_bg.css')
    if parts[0] == 'frontend':
        return (len(parts) >= 3 and parts[1] in ('src', 'public')) or name in {
            'frontend/package.json', 'frontend/package-lock.json', 'frontend/index.html',
            'frontend/vite.config.ts', 'frontend/tsconfig.json'}
    if name in ('local-launcher/settings.json', 'local-maintenance/runtime.json') or path.suffix.lower() in ('.mp4', '.db', '.sqlite', '.sqlite3', '.log', '.key'):
        return False
    return True


def source_files(root: Path) -> set[str]:
    names = set()
    for name in ROOT_FILES:
        if (root / name).is_file():
            names.add(name)
    for name in SOURCE_DIRS:
        if not (root / name).is_dir():
            continue
        for base, dirs, files in os.walk(root / name):
            dirs[:] = [d for d in dirs if d.lower() not in EXCLUDED and d != 'dist']
            if name == 'local-launcher' and Path(base) == root / name:
                dirs[:] = [d for d in dirs if d not in {'data', 'logs', 'cache'}]
            if any((Path(base) / d).is_symlink() for d in dirs):
                raise ValueError('源码目录包含未支持的符号链接。')
            for filename in files:
                path = Path(base) / filename
                relative = path.relative_to(root).as_posix()
                if source_allowed(relative):
                    if path.is_symlink():
                        raise ValueError('源码包含未支持的符号链接：' + relative)
                    names.add(relative)
    return names


class Commands:
    def __init__(self, events, log: Path):
        self.events, self.log = events, log
        self.log.parent.mkdir(parents=True, exist_ok=True)

    def cancelled(self):
        if self.events.cancelled.is_set():
            raise KeyboardInterrupt

    def run(self, arguments, cwd: Path, *, timeout=900, capture=False, env=None, check=True):
        self.cancelled()
        arguments = list(map(str, arguments))
        output = self.log.with_suffix('.capture.tmp') if capture else self.log
        with ExitStack() as stack:
            stream = stack.enter_context(output.open('wb' if capture else 'ab'))
            errors = stack.enter_context(self.log.open('ab')) if capture else subprocess.STDOUT
            process = subprocess.Popen(arguments, cwd=cwd, stdin=subprocess.DEVNULL,
                                       stdout=stream, stderr=errors, env=env,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            started = last = time.monotonic()
            try:
                while process.poll() is None:
                    self.cancelled()
                    if time.monotonic() - started > timeout:
                        raise TimeoutError('命令执行超时：' + Path(arguments[0]).name)
                    if time.monotonic() - last > 10:
                        self.events.emit('updating', 'running', '正在准备，请稍候…')
                        last = time.monotonic()
                    time.sleep(.2)
            except BaseException:
                if process.poll() is None:
                    if os.name == 'nt':
                        subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'],
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW,
                                       timeout=15)
                    if process.poll() is None:
                        process.kill()
                process.wait(timeout=15)
                raise
        data = output.read_bytes() if capture else b''
        if capture:
            output.unlink(missing_ok=True)
        if process.returncode and check:
            tail = data[-3000:] if capture else self.log.read_bytes()[-3000:]
            raise RuntimeError('命令失败：' + Path(arguments[0]).name + '\n' + tail.decode('utf-8', errors='replace'))
        return process.returncode, data


class GitSources:
    """上游 Git 对象只进入更新缓存，不进入发布目录的源码历史。"""
    def __init__(self, git: Path, cache: Path, commands: Commands):
        self.git, self.cache, self.commands = git, cache, commands
        self.repository = cache / 'upstream.git'

    def ensure(self, revision: str):
        if not re.fullmatch(r'[0-9a-f]{40}', revision):
            raise ValueError('上游提交号格式错误。')
        self.cache.mkdir(parents=True, exist_ok=True)
        if not self.repository.exists():
            self.commands.run([self.git, 'init', '--bare', self.repository], self.cache)
        command = [self.git, '--git-dir=' + str(self.repository)]
        code, _ = self.commands.run(command + ['cat-file', '-e', revision + '^{commit}'], self.cache, check=False)
        if code:
            env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
            self.commands.run(command + ['fetch', '--depth=1', '--no-tags', UPSTREAM_URL, revision], self.cache, env=env)

    def snapshot(self, revision: str) -> Path:
        self.ensure(revision)
        destination = self.cache / 'sources' / revision
        if (destination / '.complete.json').is_file():
            return destination
        destination.mkdir(parents=True, exist_ok=True)
        archive = self.cache / (revision + '.tar')
        self.commands.run([self.git, '--git-dir=' + str(self.repository), 'archive', '--format=tar',
                           '--output=' + str(archive), revision], self.cache)
        try:
            with tarfile.open(archive) as source:
                for member in source:
                    self.commands.cancelled()
                    if not member.isfile() or not source_allowed(member.name):
                        continue
                    target = (destination / member.name).resolve()
                    if not target.is_relative_to(destination.resolve()):
                        raise ValueError('上游归档路径不正确。')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with source.extractfile(member) as stream, target.open('wb') as output:
                        shutil.copyfileobj(stream, output, 1024 * 1024)
            atomic_json(destination / '.complete.json', {'revision': revision})
        finally:
            archive.unlink(missing_ok=True)
        return destination


def git_identities(current: Path, old: Path, new: Path, commands: Commands, git: Path):
    """利用已提交且未改动文件的 Git 身份，减少逐个重复读取模型与图片。"""
    repository = old.parent.parent / 'upstream.git'
    if not (current / '.git').is_dir() or not repository.is_dir():
        return {}
    maps = {}
    for root in (old, new):
        marker = root / '.complete.json'
        if not marker.is_file():
            return {}
        revision = json.loads(marker.read_text(encoding='utf-8')).get('revision', '')
        if not re.fullmatch(r'[0-9a-f]{40}', revision):
            return {}
        code, output = commands.run([git, '--git-dir=' + str(repository), 'ls-tree', '-r', '-z', revision],
                                    current, capture=True, check=False)
        if code:
            return {}
        entries = {}
        for item in output.split(b'\0'):
            if item:
                header, name = item.split(b'\t', 1)
                entries[name.decode('utf-8')] = header.split()[2]
        maps[root] = entries
    code, output = commands.run([git, '-C', current, 'diff-files', '--name-only', '-z'],
                                current, capture=True, check=False)
    if code:
        return {}
    changed = {name.decode('utf-8') for name in output.split(b'\0') if name}
    code, output = commands.run([git, '-C', current, 'ls-files', '--stage', '-z'],
                                current, capture=True, check=False)
    if code:
        return {}
    entries = {}
    for item in output.split(b'\0'):
        if item:
            header, raw = item.split(b'\t', 1)
            name = raw.decode('utf-8')
            fields = header.split()
            if name not in changed and fields[2] == b'0':
                entries[name] = fields[1]
    maps[current] = entries
    return maps


def merge_source(current: Path, old: Path, new: Path, destination: Path, commands: Commands, git: Path, *, selected=None) -> dict:
    """相同基线保留上游；本地修改采用三方合并，不用整文件覆盖上游。"""
    destination.mkdir(parents=True, exist_ok=True)
    old_names, new_names, local_names = source_files(old), source_files(new), source_files(current)
    identities = git_identities(current, old, new, commands, git)
    hashes = {}
    def same(left, right, name):
        a, b = identities.get(left, {}).get(name), identities.get(right, {}).get(name)
        if a is not None and b is not None:
            return a == b
        for root in (left, right):
            if (root, name) not in hashes:
                hashes[root, name] = content_digest(root / name)
        return hashes[left, name] == hashes[right, name]
    conflicts, modified = [], []
    names = sorted(new_names | local_names if selected is None else selected)
    last = time.monotonic()
    for number, name in enumerate(names, 1):
        commands.cancelled()
        if time.monotonic() - last > 5:
            commands.events.emit('source', 'running', '正在合并源码（' + str(number) + '/' + str(len(names)) + '）…')
            last = time.monotonic()
        local, base, upstream = current / name, old / name, new / name
        target = destination / name
        chosen = None
        if name == 'README.md' or name.startswith(('local-launcher/', 'local-maintenance/', 'local-repairs/')):
            chosen = local if name in local_names else upstream
        elif name not in old_names:
            if name in local_names and name in new_names and not same(current, new, name):
                conflicts.append(name)
                continue
            chosen = local if name in local_names else upstream
        elif name not in local_names:
            # 未打包的本地删除保持删除，新增的上游文件则由上一分支带入。
            continue
        elif same(current, old, name):
            chosen = upstream if name in new_names else None
        elif name not in new_names:
            conflicts.append(name)
            continue
        elif same(new, old, name) or same(current, new, name):
            chosen = local
        else:
            inputs = commands.log.parent / 'merge-inputs' / hashlib.sha256(name.encode()).hexdigest()[:12]
            inputs.mkdir(parents=True, exist_ok=True)
            paths = []
            for label, path in [('local', local), ('base', base), ('upstream', upstream)]:
                value = normalized_bytes(path)
                normalized = inputs / label
                normalized.write_bytes(path.read_bytes() if value is None else value)
                paths.append(normalized)
            code, data = commands.run([git, 'merge-file', '-p', '--', *paths], destination,
                                      check=False, capture=True)
            if code:
                adapter = Path(__file__).parent / 'merge-adapters'
                index = adapter / 'index.json'
                known = json.loads(index.read_text(encoding='utf-8')).get(name) if index.is_file() else None
                input_hashes = [digest(path) for path in paths]
                if known and known['inputs'] == input_hashes:
                    resolved = adapter / known['output']
                    if resolved.parent != adapter or digest(resolved) != known['sha256']:
                        raise RuntimeError('已验证的上游适配文件损坏。')
                    data = resolved.read_bytes()
                else:
                    conflicts.append(name)
                    continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            modified.append(name)
        if chosen is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(chosen, target)
            if chosen == local and name in old_names and not same(current, old, name):
                modified.append(name)
    if conflicts:
        atomic_json(destination.parent / 'merge-conflicts.json', {'files': conflicts})
        raise RuntimeError('以下本地修改需要适配新版：\n' + '\n'.join(conflicts))
    return {'merged_local_files': modified, 'source_files': len(source_files(destination))}
