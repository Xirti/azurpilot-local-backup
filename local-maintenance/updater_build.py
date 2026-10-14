"""候选环境、前端构建和独立数据副本。"""
from __future__ import annotations

import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time
import urllib.request
import zipfile

from managed_installation import atomic_json
from runtime_layout import base_python


def environment(**extra):
    values = {k: v for k, v in os.environ.items() if k.lower() not in {
        'pythonhome', 'pythonpath', 'virtual_env', '__pyvenv_launcher__', 'azurpilot_local_mode',
        'azurpilot_config_dir', 'azurpilot_shutdown_event', 'azurpilot_install_root'}}
    values.update(PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', UV_LINK_MODE='copy',
                  UV_CONCURRENT_DOWNLOADS='2', UV_CONCURRENT_INSTALLS='2')
    values.update({k: str(v) for k, v in extra.items()})
    return values


def copy_tree(source: Path, target: Path, commands, *, ignored=()):
    last = time.monotonic()
    for base, dirs, files in os.walk(source):
        commands.cancelled()
        dirs[:] = [d for d in dirs if d.lower() not in {
            '__pycache__', '.pytest_cache', 'test', 'tests', '__tests__', 'mock', 'fixtures'}
                   and d not in ignored]
        if any((Path(base) / d).is_symlink() for d in dirs):
            raise ValueError('运行环境目录包含不支持的符号链接。')
        relative = Path(base).relative_to(source)
        destination = target / relative
        destination.mkdir(parents=True, exist_ok=True)
        for name in files:
            if name.endswith(('.pyc', '.pyo')) or name in ignored:
                continue
            path = Path(base) / name
            if path.is_symlink():
                raise ValueError('运行环境包含不支持的符号链接。')
            shutil.copy2(path, destination / name)
        if time.monotonic() - last > 5:
            commands.events.emit('environment', 'running', '正在复制独立运行环境…')
            last = time.monotonic()


def prepare_python(current: Path, candidate: Path, cache: Path, commands):
    for component in ('.venv', 'python-runtime'):
        copy_tree(current / component, candidate / component, commands)
    python = base_python(candidate)
    cfg = candidate / '.venv/pyvenv.cfg'
    import re
    cfg.write_text(re.sub(r'(?m)^home\s*=.*$', lambda _: 'home = ' + str(python.parent),
                          cfg.read_text(encoding='utf-8')), encoding='utf-8')
    uv = candidate / 'python-runtime/tools/uv.exe'
    if not uv.is_file():
        found = shutil.which('uv')
        if not found:
            raise RuntimeError('随包 uv 缺失。')
        uv = Path(found)
    commands.run([uv, 'sync', '--frozen', '--no-dev', '--no-install-project', '--python', python,
                  '--project', candidate, '--cache-dir', cache / 'uv'], candidate,
                 env=environment(UV_PYTHON_INSTALL_DIR=candidate / 'python-runtime'), timeout=1200)
    return python


def download(url: str, target: Path, commands):
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={'User-Agent': 'AzurPilot-Local-Updater'})
    temporary = target.with_suffix(target.suffix + '.partial')
    try:
        with urllib.request.urlopen(request, timeout=30) as source, temporary.open('wb') as stream:
            last = time.monotonic()
            while chunk := source.read(1024 * 1024):
                commands.cancelled()
                stream.write(chunk)
                if time.monotonic() - last > 5:
                    commands.events.emit('download', 'running', '正在下载构建工具…')
                    last = time.monotonic()
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def node_runtime(tools: Path, commands) -> Path:
    cached = tools / 'node.json'
    if cached.is_file():
        record = json.loads(cached.read_text(encoding='utf-8'))
        path = (tools / record['directory'] / 'node.exe').resolve()
        if path.is_relative_to(tools.resolve()) and path.is_file():
            return path
    installed = shutil.which('node')
    if installed:
        code, version = commands.run([installed, '--version'], tools.parent, capture=True, check=False)
        numbers = tuple(int(n) for n in version.decode().strip().lstrip('v').split('.')[:3]) if not code else ()
        npm = Path(installed).parent / 'node_modules/npm/bin/npm-cli.js'
        if numbers >= (22, 12, 0) and npm.is_file():
            return Path(installed)
    tools.mkdir(parents=True, exist_ok=True)
    index = tools / 'node-index.json'
    download('https://nodejs.org/dist/index.json', index, commands)
    releases = json.loads(index.read_text(encoding='utf-8'))
    record = next(item for item in releases if item['version'].startswith('v22.') and 'win-x64-zip' in item['files'])
    version = record['version']
    filename = 'node-' + version + '-win-x64.zip'
    checksums = tools / 'node-checksums.txt'
    download('https://nodejs.org/dist/' + version + '/SHASUMS256.txt', checksums, commands)
    expected = next(line.split()[0] for line in checksums.read_text().splitlines() if line.split()[-1] == filename)
    archive = tools / filename
    download('https://nodejs.org/dist/' + version + '/' + filename, archive, commands)
    with archive.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
            raise RuntimeError('Node.js 下载校验失败。')
    with zipfile.ZipFile(archive) as source:
        for member in source.infolist():
            commands.cancelled()
            target = (tools / member.filename).resolve()
            if not target.is_relative_to(tools.resolve()):
                raise ValueError('构建工具归档路径错误。')
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(member) as stream, target.open('wb') as output:
                    shutil.copyfileobj(stream, output)
    directory = 'node-' + version + '-win-x64'
    atomic_json(cached, {'directory': directory, 'version': version})
    archive.unlink()
    return tools / directory / 'node.exe'


def build_frontend(candidate: Path, previous: Path, state: Path, commands):
    node = node_runtime(state / 'tools', commands)
    frontend = candidate / 'frontend'
    key = hashlib.sha256((frontend / 'package-lock.json').read_bytes()).hexdigest()[:20]
    build = state / 'build' / ('frontend-' + key)
    build.mkdir(parents=True, exist_ok=True)
    # 构建依赖留在更新缓存中，版本目录只保留源码与产物。
    for name in ('src', 'public'):
        if (build / name).exists():
            path = (build / name).resolve()
            if not path.is_relative_to((state / 'build').resolve()):
                raise ValueError('构建缓存目录错误。')
            shutil.rmtree(path)
        if (frontend / name).is_dir():
            shutil.copytree(frontend / name, build / name)
    for name in ('package.json', 'package-lock.json', 'index.html', 'vite.config.ts', 'tsconfig.json'):
        shutil.copy2(frontend / name, build / name)
    npm = node.parent / 'node_modules/npm/bin/npm-cli.js'
    env = environment(PATH=str(node.parent) + os.pathsep + os.environ.get('PATH', ''),
                      NODE_OPTIONS='--max-old-space-size=1536')
    ready = build / '.dependencies-ready.json'
    installed = json.loads(ready.read_text(encoding='utf-8')).get('lock') if ready.is_file() else None
    if not (build / 'node_modules').is_dir() or installed != key:
        ready.unlink(missing_ok=True)
        commands.run([node, npm, 'ci', '--no-audit', '--no-fund', '--cache', state / 'cache/npm'],
                     build, env=env, timeout=1200)
        atomic_json(ready, {'lock': key})
    commands.run([node, npm, 'run', 'build'], build, env=env, timeout=1200)
    destination = frontend / 'dist'
    if destination.exists():
        path = destination.resolve()
        if path.parent != frontend.resolve():
            raise ValueError('前端产物目录错误。')
        shutil.rmtree(path)
    shutil.copytree(build / 'dist', destination)
    for name in ('JetBrainsMonoNL-Regular.ttf', 'MiSans-Demibold.ttf'):
        if not (destination / name).is_file() and (previous / 'frontend/dist' / name).is_file():
            shutil.copy2(previous / 'frontend/dist' / name, destination / name)
    commands.run([candidate / '.venv/Scripts/python.exe', '-B', '-X', 'utf8', '-c',
                  'from deploy.frontend import source_fingerprint;from pathlib import Path;'
                  'p=Path("frontend");(p/"dist/.source-fingerprint").write_text(source_fingerprint(p)+chr(10),encoding="utf-8")'],
                 candidate, env=environment())


def backup_data(source: Path, target: Path, commands) -> dict:
    """SQLite 使用备份 API；同时保留普通配置和旧版日志中的业务数据。"""
    paths = [p for p in (source / 'config').rglob('*') if p.is_file()]
    for pattern in ('cl1/**/*.json', 'cl1/**/*.json.bak', 'cl1/**/*.db', 'azurstat_meowofficer_farming*.csv',
                    'device_id.json', 'device_id.json.bak'):
        paths.extend(p for p in (source / 'log').glob(pattern) if p.is_file())
    copied = []
    for path in sorted(set(paths)):
        commands.cancelled()
        if path.is_symlink() or not path.resolve().is_relative_to(source.resolve()):
            raise ValueError('数据目录包含安装目录之外的链接。')
        if path.name.endswith(('.lock', '-wal', '-shm', '-journal', '.tmp')):
            continue
        relative = path.relative_to(source)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with path.open('rb') as stream:
            sqlite = stream.read(16) == b'SQLite format 3\x00'
        if sqlite:
            with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as original:
                with closing(sqlite3.connect(destination)) as output:
                    original.backup(output, pages=256)
        else:
            shutil.copy2(path, destination)
        copied.append(relative.as_posix())
    atomic_json(target / 'backup.json', {'files': copied, 'private': True})
    return {'files': len(copied)}
