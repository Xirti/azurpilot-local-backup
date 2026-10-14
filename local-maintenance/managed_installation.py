"""固定入口下的版本选择、更新锁和事务记录。"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time

UPSTREAM_URL = 'https://github.com/wess09/AzurPilot.git'
UPSTREAM_BRANCH = 'master'


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding='utf-8-sig'))


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(20):
            try:
                os.replace(name, path)
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(.05)
    finally:
        Path(name).unlink(missing_ok=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class Installation:
    """所有切换都只指向安装目录内已完成验收的版本。"""
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.state = self.root / '.updates'
        self.pointer = self.state / 'current.json'

    def relative(self, value: str) -> Path:
        if value == '.':
            return self.root
        if not re.fullmatch(r'versions/[A-Za-z0-9][A-Za-z0-9._-]{0,119}', value):
            raise ValueError('版本目录记录不正确。')
        path = self.root / value
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise ValueError('版本目录不能指向安装目录之外。')
        return path.resolve()

    def record(self) -> dict:
        value = read_json(self.pointer, {'schema_version': 1, 'active': '.', 'previous': None})
        if not isinstance(value, dict) or value.get('schema_version') != 1:
            raise ValueError('当前版本记录无法读取。')
        self.relative(value['active'])
        if value.get('previous') is not None:
            self.relative(value['previous'])
        return value

    def active_root(self) -> Path:
        return self.relative(self.record()['active'])

    def require_active(self, root: Path) -> None:
        if root.resolve() != self.active_root():
            raise RuntimeError('当前窗口使用的版本已经切换，请重新打开启动器。')

    def describe(self) -> dict:
        record = self.record()
        active = self.active_root()
        provenance = read_json(active / 'local-maintenance/provenance.json', {})
        manifest = read_json(active / 'local-repairs/manifest.json', {})
        checked = read_json(self.state / 'checked.json', {})
        return {'current_version': manifest.get('revision_ref', '').removeprefix('refs/tags/'),
                'upstream_revision': provenance.get('upstream_revision', ''),
                'checked_revision': checked.get('revision', ''),
                'checked_summary': checked.get('summary', ''),
                'rollback_available': record.get('previous') is not None,
                'source': UPSTREAM_URL, 'branch': UPSTREAM_BRANCH}

    def activate(self, version: str, validation: dict) -> dict:
        if not validation.get('passed'):
            raise RuntimeError('候选版本尚未通过验收。')
        target = self.relative(version)
        if not (target / 'local-repairs/manifest.json').is_file():
            raise RuntimeError('候选版本不完整。')
        previous = self.record()
        if previous['active'] == version:
            return previous
        value = {'schema_version': 1, 'active': version, 'previous': previous['active'],
                 'activated_at': utc_now(), 'validation': validation}
        atomic_json(self.pointer, value)
        return value

    def rollback(self) -> dict:
        current = self.record()
        previous = current.get('previous')
        if previous is None:
            raise RuntimeError('还没有可回退的上一版本。')
        target = self.relative(previous)
        if not (target / 'local-repairs/manifest.json').is_file():
            raise RuntimeError('上一版本文件缺失。')
        value = {'schema_version': 1, 'active': previous, 'previous': current['active'],
                 'activated_at': utc_now(), 'rolled_back': True}
        atomic_json(self.pointer, value)
        return value

    @contextmanager
    def locked(self):
        self.state.mkdir(parents=True, exist_ok=True)
        with (self.state / 'operation.lock').open('a+b') as stream:
            if os.fstat(stream.fileno()).st_size == 0:
                stream.write(b'1')
                stream.flush()
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as error:
                    raise RuntimeError('另一个更新或回退任务正在执行。') from error
            else:
                import fcntl
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as error:
                    raise RuntimeError('另一个更新或回退任务正在执行。') from error
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)


def for_active(root: Path) -> Installation:
    install = Installation(Path(os.environ.get('AZURPILOT_INSTALL_ROOT', root)))
    install.require_active(root)
    return install
