"""解压后离线初始化：保留已有私人配置，只为缺失文件创建公共默认值。"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import maintain


def initialize_git(root: Path, check_only: bool) -> None:
    """仅为完整离线包导入随包源码历史；已有 Git 目录交给版本校验。"""
    if (root / '.git').exists():
        return
    bundle = root / 'local-maintenance/offline-artifacts/source.bundle'
    if check_only or not bundle.is_file():
        raise RuntimeError('源码版本记录缺失，请运行完整离线包的初始化入口。')
    git = str(root / '.venv/Scripts/git/cmd/git.exe')
    manifest = maintain.read_json(root / 'local-repairs/manifest.json')
    reference = manifest['revision_ref']
    if not reference.startswith('refs/tags/'):
        raise ValueError('离线版本标签格式错误。')
    flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}
    def run(*arguments):
        subprocess.run([git, '-C', str(root), *arguments], check=True, capture_output=True,
                       timeout=180, **flags)
    run('init')
    run('config', '--local', 'core.autocrlf', 'false')
    run('fetch', '--no-tags', str(bundle), 'refs/heads/main:refs/heads/main',
        reference + ':' + reference)
    run('symbolic-ref', 'HEAD', 'refs/heads/main')
    run('read-tree', 'HEAD')
    run('remote', 'add', 'origin', 'https://github.com/Xirti/azurpilot-local-backup.git')
    run('config', '--local', 'branch.main.remote', 'origin')
    run('config', '--local', 'branch.main.merge', 'refs/heads/main')


def initialize(root: Path, check_only: bool = False) -> dict:
    maintain.assert_stopped(root)
    for relative in ['.venv/Scripts/python.exe', '.venv/Scripts/git/cmd/git.exe',
                     'python-runtime/cpython-3.14.6-windows-x86_64-none/python.exe']:
        if not (root / relative).is_file():
            raise RuntimeError(f'完整离线运行环境缺失：{relative}')
    initialize_git(root, check_only)
    config_path = root / 'config/alas2.json'
    deploy_path = root / 'config/deploy.yaml'
    created = []
    if not check_only:
        profile = maintain.load_profile()
        if not config_path.is_file():
            data = maintain.read_json(root / 'config/template.json')
            # 只对首次创建的公共默认实例使用本机原值，不覆盖已有用户选择。
            for item in profile['preserve_user_settings']:
                maintain.set_existing(data, item['path'], item['original_value'])
            config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n',
                                   encoding='utf-8', newline='\n')
            created.append('config/alas2.json')
        if not deploy_path.is_file():
            text = (root / 'config/deploy.template.yaml').read_text(encoding='utf-8-sig')
            values = dict(profile['deployment'], InstallDependencies=False,
                          ReplaceAdb=False, AutoConnect=False)
            for name, value in values.items():
                text = maintain.replace_deployment(text, name, value)
            deploy_path.write_text(text, encoding='utf-8', newline='\n')
            created.append('config/deploy.yaml')
        result = maintain.restore(root, 'alas2', pause_monthly=True)
    else:
        result = {}
    spec = importlib.util.spec_from_file_location('release_launcher', root / 'local-repairs/webui_launcher.py')
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    manifest = launcher.verify_repair(root)
    audit = maintain.audit(root, 'alas2')
    if not audit['configuration_matches'] or not all(audit['repair_hashes'].values()):
        raise RuntimeError('本地配置或修复校验未通过，请检查本地设置。')
    return {'created_public_configuration': created,
            'existing_user_configuration_preserved': 'config/alas2.json' not in created,
            'revision': manifest['verified_revision'], 'guarded_files': len(manifest['files']),
            'game_started': False, **result}


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
