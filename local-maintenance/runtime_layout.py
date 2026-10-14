"""寻找随包基础解释器，不把补丁绑定到某个 Python 小版本。"""
from pathlib import Path
import json
import re


def base_python(root: Path) -> Path:
    root = root.resolve()
    info = root / 'local-maintenance/offline-artifacts/release-runtime.json'
    if info.is_file():
        relative = json.loads(info.read_text(encoding='utf-8-sig')).get('runtime_python')
        if relative:
            path = (root / relative).resolve()
            if path.is_relative_to(root / 'python-runtime') and path.is_file():
                return path
    candidates = list((root / 'python-runtime').glob('cpython-*-windows-x86_64-none/python.exe'))
    candidates.sort(key=lambda p: tuple(int(n) for n in re.findall(r'\d+', p.parent.name)[:3]), reverse=True)
    if not candidates:
        raise RuntimeError('随包基础 Python 缺失。')
    return candidates[0]
