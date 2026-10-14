"""解压后离线初始化：保留已有私人配置，只为缺失文件创建公共默认值。"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import maintain
from runtime_layout import base_python


def initialize_git(root: Path, check_only: bool, cancelled=None) -> None:
    """仅为完整离线包导入随包源码历史；已有 Git 目录交给版本校验。"""
    bundle = root / 'local-maintenance/offline-artifacts/source.bundle'
    git = str(root / '.venv/Scripts/git/cmd/git.exe')
    manifest = maintain.read_json(root / 'local-repairs/manifest.json')
    reference = manifest['revision_ref']
    if not reference.startswith('refs/tags/'):
        raise ValueError('离线版本标签格式错误。')
    flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}
    def run(*arguments, check=True):
        if cancelled is not None and cancelled():
            raise KeyboardInterrupt
        command = [git, '-C', str(root), *arguments]
        # 启动后端持续读取控制管道；Git 必须使用独立输入，否则 Windows 下会阻塞。
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, **flags)
        started = time.monotonic()
        next_message = started + 10
        try:
            while True:
                if cancelled is not None and cancelled():
                    raise KeyboardInterrupt
                remaining = 180 - (time.monotonic() - started)
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, 180)
                try:
                    stdout, stderr = process.communicate(timeout=min(.2, remaining))
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() >= next_message:
                        print('[初始化] 正在准备本地版本记录，可查看启动日志或中断。', flush=True)
                        next_message = time.monotonic() + 10
                    continue
        except BaseException:
            if process.poll() is None:
                process.kill()
            process.communicate()
            raise
        result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        if check:
            result.check_returncode()
        return result
    if (root / '.git').exists():
        if run('rev-parse', '--verify', 'HEAD^{commit}', check=False).returncode == 0:
            return
        # 上次在 init 后中断时仅留下空仓库，可继续导入；已有分支和索引不覆盖。
        refs = run('show-ref', check=False)
        if refs.returncode != 1 or (root / '.git/index').exists():
            raise RuntimeError('版本记录未完成且包含已有内容，请先检查 .git。')
    if check_only or not bundle.is_file():
        raise RuntimeError('源码版本记录缺失，请通过启动器初始化完整离线包。')
    run('init')
    run('config', '--local', 'core.autocrlf', 'false')
    run('fetch', '--update-head-ok', '--no-tags', str(bundle), 'refs/heads/main:refs/heads/main',
        reference + ':' + reference)
    run('symbolic-ref', 'HEAD', 'refs/heads/main')
    run('read-tree', 'HEAD')
    if run('remote', 'get-url', 'origin', check=False).returncode:
        run('remote', 'add', 'origin', 'https://github.com/Xirti/azurpilot-local-backup.git')
    run('config', '--local', 'branch.main.remote', 'origin')
    run('config', '--local', 'branch.main.merge', 'refs/heads/main')


def initialize(root: Path, check_only: bool = False, cancelled=None) -> dict:
    maintain.assert_stopped(root)
    for relative in ['.venv/Scripts/python.exe', '.venv/Scripts/git/cmd/git.exe']:
        if not (root / relative).is_file():
            raise RuntimeError(f'完整离线运行环境缺失：{relative}')
    base_python(root)
    initialize_git(root, check_only, cancelled)
    deploy_path = root / 'config/deploy.yaml'
    created = []
    if not check_only:
        profile = maintain.load_profile()
        if not deploy_path.is_file():
            text = (root / 'config/deploy.template.yaml').read_text(encoding='utf-8-sig')
            values = dict(profile['deployment'], InstallDependencies=False,
                          ReplaceAdb=False, AutoConnect=False)
            for name, value in values.items():
                text = maintain.replace_deployment(text, name, value)
            deploy_path.write_text(text, encoding='utf-8', newline='\n')
            created.append('config/deploy.yaml')
    spec = importlib.util.spec_from_file_location('release_launcher', root / 'local-repairs/webui_launcher.py')
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    manifest = launcher.verify_repair(root)
    audit = maintain.audit(root, '')
    if not audit['configuration_matches'] or not all(audit['repair_hashes'].values()):
        raise RuntimeError('本地配置或修复校验未通过，请检查本地设置。')
    return {'created_public_configuration': created,
            'existing_user_configuration_preserved': True,
            'revision': manifest['verified_revision'], 'guarded_files': len(manifest['files']),
            'game_started': False, 'instances': maintain.instance_names(root)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=HERE.parent)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(initialize(args.root.resolve(), args.check), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'[离线初始化失败] {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
