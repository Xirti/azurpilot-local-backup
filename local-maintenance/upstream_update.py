"""手动触发的上游更新：准备独立版本，验收后切换固定入口。"""
from __future__ import annotations

from datetime import datetime, timezone
from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import subprocess
import urllib.request
import uuid

from managed_installation import Installation, UPSTREAM_URL, UPSTREAM_BRANCH, atomic_json, digest, utc_now
from runtime_layout import base_python
from updater_build import backup_data, build_frontend, copy_tree, environment, prepare_python
from updater_sources import Commands, GitSources, merge_source, source_files


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git_binary(root: Path) -> Path:
    bundled = root / '.venv/Scripts/git/cmd/git.exe'
    found = str(bundled) if bundled.is_file() else shutil.which('git')
    if not found:
        raise RuntimeError('随包 Git 缺失。')
    return Path(found)


def check(root: Path, installation: Installation, events) -> dict:
    commands = Commands(events, events.path.with_suffix('.command.txt'))
    events.emit('checking', 'running', '正在检查上游版本…')
    _, output = commands.run([git_binary(root), 'ls-remote', UPSTREAM_URL, 'refs/heads/' + UPSTREAM_BRANCH],
                              root, capture=True, timeout=120, env=environment(GIT_TERMINAL_PROMPT='0'))
    revision = output.decode('utf-8').split()[0] if output.strip() else ''
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise RuntimeError('没有获取到有效的上游版本。')
    summary = ''
    try:
        request = urllib.request.Request('https://api.github.com/repos/wess09/AzurPilot/commits/' + revision,
                                         headers={'User-Agent': 'AzurPilot-Local-Updater',
                                                  'Accept': 'application/vnd.github+json'})
        with urllib.request.urlopen(request, timeout=10) as response:
            summary = json.load(response)['commit']['message'].splitlines()[0][:250]
    except (OSError, ValueError, KeyError):
        pass
    record = {'source': UPSTREAM_URL, 'branch': UPSTREAM_BRANCH, 'revision': revision,
              'summary': summary, 'checked_at': utc_now()}
    atomic_json(installation.state / 'checked.json', record)
    current = json.loads((root / 'local-maintenance/provenance.json').read_text(encoding='utf-8'))
    return {'state': 'succeeded', 'available': current['upstream_revision'] != revision,
            'current_revision': current['upstream_revision'], **record}


def stop_service(root: Path):
    stop = load(root / 'local-repairs/webui_stop.py', 'update_owned_stop')
    stop.stop(root)


def preserve_values(root: Path) -> dict:
    paths = ('CloseEmulatorDuringLongWait', 'WhenTaskQueueEmpty', 'WhenSchedulerStopped')
    values = {}
    for path in (root / 'config').glob('*.json'):
        if path.name.startswith('template'):
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8-sig'))
            optimization = data['Alas']['Optimization']
            values[path.name] = {name: optimization[name] for name in paths}
        except (ValueError, KeyError, TypeError):
            continue
    return values


def pin_version(current: Path, candidate: Path, upstream: str, tag: str, commands: Commands, job: Path, *, inherit_history=True):
    git = git_binary(candidate)
    def run(*args, capture=False, check=True):
        return commands.run([git, '-c', 'pack.threads=2', '-c', 'pack.windowMemory=64m', '-C', candidate, *args],
                            candidate, capture=capture, check=check)
    run('init', '-b', 'main')
    run('config', 'core.autocrlf', 'false')
    run('config', 'core.longpaths', 'true')
    run('config', 'user.name', 'AzurPilot Local')
    run('config', 'user.email', 'local@localhost')
    bundle = current / 'local-maintenance/offline-artifacts/source.bundle'
    has_head, _ = run('rev-parse', '--verify', '--quiet', 'HEAD', check=False, capture=True)
    if has_head and inherit_history and bundle.is_file():
        run('fetch', '--update-head-ok', '--no-tags', bundle, 'refs/heads/main:refs/heads/main')
        run('read-tree', 'HEAD')
    provenance_path = candidate / 'local-maintenance/provenance.json'
    provenance = json.loads(provenance_path.read_text(encoding='utf-8-sig'))
    provenance.update(upstream_url=UPSTREAM_URL.removesuffix('.git'), upstream_revision=upstream,
                      upstream_branch=UPSTREAM_BRANCH, updated_at=utc_now(), update_engine_version=1)
    atomic_json(provenance_path, provenance)
    path = candidate / 'local-repairs/manifest.json'
    manifest = json.loads(path.read_text(encoding='utf-8-sig'))
    names = {n for n in manifest['files'] if not n.startswith('frontend/dist/') and (candidate / n).is_file()}
    names.update(p.relative_to(candidate).as_posix() for p in (candidate / 'frontend/dist').rglob('*') if p.is_file())
    names.update(n for n in source_files(candidate) if n.startswith(('local-maintenance/', 'local-launcher/')))
    names.discard('local-repairs/manifest.json')
    manifest.update(revision_ref='refs/tags/' + tag, upstream_revision=upstream)
    manifest['files'] = {n: digest(candidate / n) for n in sorted(names)}
    atomic_json(path, manifest)
    names = source_files(candidate) | {p.relative_to(candidate).as_posix() for p in (candidate / 'frontend/dist').rglob('*') if p.is_file()}
    _, old = run('ls-files', '-z', capture=True)
    names.update(n for n in old.decode('utf-8').split('\0') if n)
    pathspec = job / 'source-paths.bin'
    pathspec.write_bytes(b'\0'.join(n.encode('utf-8') for n in sorted(names)) + b'\0')
    run('add', '-A', '--pathspec-from-file=' + str(pathspec), '--pathspec-file-nul')
    # 更新只检查新增差异；全新发行快照包含上游旧文件，不改写模型和许可证的原有空白。
    if inherit_history:
        run('diff', '--cached', '--check')
    run('commit', '-m', '接入上游 ' + upstream[:12] + '，保留本地启动与配置方案')
    run('tag', tag)
    _, revision = run('rev-parse', 'HEAD', capture=True)
    artifact = candidate / 'local-maintenance/offline-artifacts'
    artifact.mkdir(parents=True, exist_ok=True)
    run('bundle', 'create', artifact / 'source.bundle', 'main', 'refs/tags/' + tag)
    run('bundle', 'verify', artifact / 'source.bundle')
    python = base_python(candidate)
    atomic_json(artifact / 'release-runtime.json', {
        'tag': tag, 'revision': revision.decode().strip(), 'upstream_revision': upstream,
        'runtime_python': python.relative_to(candidate).as_posix(),
        'platform': 'Windows-x64', 'start_entry': 'AzurPilot-Local.exe',
        'initialize_entry': 'AzurPilot-Local.exe（首次启动自动准备）',
        'private_configuration_included': False, 'source_bundle_verified': True})


def verify_candidate(candidate: Path, commands: Commands, preserved: dict) -> dict:
    python = candidate / '.venv/Scripts/python.exe'
    commands.events.emit('validation', 'running', '正在检查游戏运行模块…')
    commands.run([python, '-B', '-X', 'utf8', '-c',
                  'import scipy.signal;from module.os.map import OSMap;'
                  'from module.handler.login import LoginHandler;print("TASK_IMPORTS_OK")'],
                 candidate, env=environment(), timeout=180)
    commands.events.emit('migration', 'running', '正在检查数据迁移…')
    commands.run([python, '-B', '-X', 'utf8', candidate / 'local-maintenance/migrate_candidate.py'],
                 candidate, env=environment(), timeout=900)
    database = candidate / 'config/azurpilot.db'
    with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as connection:
        if connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise RuntimeError('候选数据库检查失败。')
    commands.events.emit('validation', 'running', '正在验证本地服务与页面…')
    # 测试使用独立端口；正式部署文件在 finally 中恢复原值。
    deploy = candidate / 'config/deploy.yaml'
    original = deploy.read_bytes()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    text = original.decode('utf-8-sig')
    replaced, count = re.subn(r'(?m)^(\s*WebuiPort:\s*)\d+', lambda m: m[1] + str(port), text)
    if count != 1:
        raise RuntimeError('候选 WebUI 端口配置不能确定。')
    deploy.write_text(replaced, encoding='utf-8')
    backend = candidate / 'local-launcher/backend.py'
    try:
        commands.run([python, '-B', '-X', 'utf8', backend, 'start', '--root', candidate],
                     candidate, env=environment(), timeout=300)
        with urllib.request.urlopen('http://127.0.0.1:' + str(port) + '/healthz', timeout=5) as response:
            if json.load(response).get('status') != 'ok':
                raise RuntimeError('候选服务健康检查未通过。')
        with urllib.request.urlopen('http://127.0.0.1:' + str(port) + '/', timeout=5) as response:
            if response.status != 200:
                raise RuntimeError('候选页面未正常加载。')
        registry = json.loads((candidate / 'cache/webui-workers.json').read_text(encoding='utf-8'))
        if registry.get('workers'):
            raise RuntimeError('候选验证期间意外启动了任务。')
        if preserve_values(candidate) != preserved:
            raise RuntimeError('候选配置改变了原有等待、队列或停止行为。')
    finally:
        try:
            commands.run([python, '-B', '-X', 'utf8', backend, 'stop', '--root', candidate],
                         candidate, env=environment(), timeout=90)
        finally:
            deploy.write_bytes(original)
    return {'passed': True, 'database': 'ok', 'webui': True, 'game_tasks_started': 0,
            'user_wait_settings_preserved': True, 'verified_at': utc_now()}


def update(root: Path, installation: Installation, events, *, source_factory=GitSources) -> dict:
    with installation.locked():
        installation.require_active(root)
        launcher = load(root / 'local-repairs/webui_launcher.py', 'update_version_guard')
        current_manifest = launcher.verify_repair(root)
        checked_path = installation.state / 'checked.json'
        if not checked_path.is_file():
            check(root, installation, events)
        checked = json.loads(checked_path.read_text(encoding='utf-8'))
        if checked.get('source') != UPSTREAM_URL or checked.get('branch') != UPSTREAM_BRANCH:
            raise ValueError('已检查的更新来源不正确。')
        target = checked['revision']
        if not re.fullmatch(r'[0-9a-f]{40}', target):
            raise ValueError('已检查的提交号不正确。')
        provenance = json.loads((root / 'local-maintenance/provenance.json').read_text(encoding='utf-8-sig'))
        if provenance['upstream_revision'] == target:
            return {'state': 'succeeded', 'up_to_date': True, 'restart_required': False}
        identifier = 'u-' + target[:12] + '-' + uuid.uuid4().hex[:8]
        candidate = installation.relative('versions/' + identifier)
        job = installation.state / 'jobs' / identifier
        job.mkdir(parents=True)
        candidate.mkdir(parents=True)
        commands = Commands(events, job / 'commands.log')
        state = {'id': identifier, 'source_revision': provenance['upstream_revision'],
                 'target_revision': target, 'current_root': str(root),
                 'candidate': 'versions/' + identifier, 'status': 'preparing', 'created_at': utc_now()}
        atomic_json(job / 'job.json', state)
        try:
            events.emit('stopping', 'running', '正在正常关闭后台…')
            stop_service(root)
            preserved = preserve_values(root)
            events.emit('backup', 'running', '正在备份配置和业务数据…')
            backup = installation.state / 'backups' / identifier
            backup_data(root, backup, commands)
            events.emit('source', 'running', '正在获取并合并上游源码…')
            sources = source_factory(git_binary(root), installation.state / 'cache', commands)
            old = sources.snapshot(provenance['upstream_revision'])
            new = sources.snapshot(target)
            merge = merge_source(root, old, new, candidate, commands, git_binary(root))
            events.emit('environment', 'running', '正在准备独立运行环境…')
            prepare_python(root, candidate, installation.state / 'cache', commands)
            backup_data(backup, candidate, commands)
            events.emit('frontend', 'running', '正在构建前端…')
            build_frontend(candidate, root, installation.state, commands)
            events.emit('version', 'running', '正在固定本地版本…')
            tag = 'local-' + identifier
            pin_version(root, candidate, target, tag, commands, job)
            validation = verify_candidate(candidate, commands, preserved)
            commands.cancelled()
            state.update(status='validated', validation=validation, merge=merge, tag=tag)
            atomic_json(job / 'job.json', state)
            events.emit('switch', 'running', '验收通过，正在切换新版…')
            record = installation.activate('versions/' + identifier, validation)
            return {'state': 'succeeded', 'restart_required': True, 'version': tag,
                    'upstream_revision': target, 'rollback_available': True, 'validation': validation}
        except BaseException as error:
            state.update(status='cancelled' if isinstance(error, KeyboardInterrupt) else 'failed',
                         error=str(error), failed_at=utc_now())
            atomic_json(job / 'job.json', state)
            raise


def rollback(root: Path, installation: Installation, events) -> dict:
    with installation.locked():
        installation.require_active(root)
        record = installation.record()
        previous = record.get('previous')
        if previous is None:
            raise RuntimeError('还没有可回退的上一版。')
        target = installation.relative(previous)
        guard = load(target / 'local-repairs/webui_launcher.py', 'rollback_version_guard')
        guard.verify_repair(target)
        events.emit('stopping', 'running', '正在正常关闭当前后台…')
        stop_service(root)
        installation.rollback()
        return {'state': 'succeeded', 'restart_required': True, 'rolled_back': True,
                'message': '已恢复上一版本及其数据。'}
