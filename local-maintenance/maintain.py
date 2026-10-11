"""本机配置审计、备份、逐项恢复和新版候选目录补丁工具。"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent


def load_profile():
    return json.loads((HERE / 'machine-profile.json').read_text(encoding='utf-8-sig'))


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def get_path(data, path):
    for part in path.split('.'):
        if not isinstance(data, dict) or part not in data:
            raise KeyError(path)
        data = data[part]
    return data


def set_existing(data, path, value):
    parts = path.split('.')
    target = data
    for part in parts[:-1]:
        if not isinstance(target, dict) or part not in target:
            raise KeyError(path)
        target = target[part]
    if parts[-1] not in target:
        raise KeyError(path)
    target[parts[-1]] = value


def replace_deployment(text, name, value):
    """只改精确存在且唯一的 YAML 叶子，不重写注释和其它部署项。"""
    pattern = rf'^([ \t]*{re.escape(name)}:[ \t]*)[^\r\n#]*(.*)$'
    matches = list(re.finditer(pattern, text, re.MULTILINE))
    if len(matches) != 1:
        raise ValueError(f'部署键缺失或重复：{name}；需要核对新版部署结构。')
    scalar = 'null' if value is None else ('true' if value is True else 'false' if value is False else str(value))
    return re.sub(pattern, lambda m: m[1] + scalar + (' ' if m[2].startswith('#') else '') + m[2],
                  text, count=1, flags=re.MULTILINE)


def flatten(data):
    result = {}
    for key, value in data.items():
        if isinstance(value, dict):
            nested = flatten(value)
            if result.keys() & nested.keys():
                raise ValueError('部署文件含重复叶子名，停止自动恢复。')
            result.update(nested)
        else:
            if key in result:
                raise ValueError('部署文件含重复叶子名。')
            result[key] = value
    return result


def assert_stopped(root):
    registry = root / 'cache/webui-workers.json'
    if registry.is_file():
        import psutil
        data = read_json(registry)
        pid, created = data.get('owner_pid'), data.get('owner_created_at')
        if pid and created is not None:
            try:
                process = psutil.Process(int(pid))
                if abs(process.create_time() - float(created)) < 0.01 and process.is_running():
                    raise RuntimeError('请先正常关闭这个目录的 WebUI，再恢复配置。')
            except psutil.NoSuchProcess:
                pass
        if data.get('workers'):
            raise RuntimeError('仍有任务登记，先核对正常退出状态。')


def backup(root):
    """私人备份置于仓库同级；不进入任何 Git 源码提交。"""
    assert_stopped(root)
    base = root.parent / (root.name + '_Private_Backup')
    target = base / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    if target.resolve().is_relative_to(root.resolve()):
        raise ValueError('私人备份不能位于源码仓库内。')
    target.mkdir(parents=True)
    shutil.copytree(root / 'config', target / 'config',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.tmp'))
    (target / '说明.txt').write_text('此目录含私人配置和任务状态，仅保留在本机，禁止加入 GitHub。\n', encoding='utf-8')
    return target


def restore(root, config, pause_monthly=False):
    assert_stopped(root)
    if not re.fullmatch(r'[A-Za-z0-9_-]+', config):
        raise ValueError('实例名只能使用字母、数字、下划线和短横线。')
    profile = load_profile()
    config_path = root / 'config' / (config + '.json')
    data = read_json(config_path)
    # 先计算所有变更，缺少任一字段就不写回半份配置。
    changes = []
    for item in profile['settings']:
        before = get_path(data, item['path'])
        if before != item['value']:
            set_existing(data, item['path'], item['value'])
            changes.append(item['path'])
    if pause_monthly:
        for task in profile['pause_monthly_tasks']:
            for key, value in [('Enable', False), ('Sensitive', True)]:
                path = f'{task}.Scheduler.{key}'
                if get_path(data, path) != value:
                    set_existing(data, path, value)
                    changes.append(path)
    deployment_path = root / 'config/deploy.yaml'
    text = deployment_path.read_text(encoding='utf-8-sig')
    current = flatten(yaml.safe_load(text))
    for name, value in profile['deployment'].items():
        if name not in current:
            raise KeyError(f'新版缺少部署项 {name}')
        if current[name] != value:
            text = replace_deployment(text, name, value)
            changes.append('deploy.' + name)
    target = backup(root)
    # 在同目录创建临时文件后替换，避免中断留下不完整 JSON。
    for path, content in [(config_path, json.dumps(data, ensure_ascii=False, indent=2) + '\n'),
                          (deployment_path, text)]:
        temporary = path.with_name(path.name + '.local-restore.tmp')
        temporary.write_text(content, encoding='utf-8', newline='\n')
        temporary.replace(path)
    return {'changed_paths': changes, 'private_backup': str(target), 'game_started': False}


def audit(root, config):
    profile = load_profile()
    data = read_json(root / 'config' / (config + '.json'))
    deployment = flatten(yaml.safe_load((root / 'config/deploy.yaml').read_text(encoding='utf-8-sig')))
    discrepancies = []
    for item in profile['settings']:
        try:
            value = get_path(data, item['path'])
        except KeyError:
            discrepancies.append({'path': item['path'], 'label': item['label'], 'missing': True})
            continue
        if value != item['value']:
            discrepancies.append({'path': item['path'], 'label': item['label'],
                                  'actual': value, 'expected': item['value']})
    for name, value in profile['deployment'].items():
        if deployment.get(name) != value:
            discrepancies.append({'path': 'deploy.'+name, 'actual': deployment.get(name), 'expected': value})
    manifest = read_json(root / 'local-repairs/manifest.json')
    hashes = {name: (root / name).is_file() and hashlib.sha256((root / name).read_bytes()).hexdigest() == expected
              for name, expected in manifest['files'].items()}
    result = {'root': str(root), 'configuration_matches': not discrepancies,
              'discrepancies': discrepancies, 'repair_hashes': hashes,
              'monthly_tasks': {task: {key: get_path(data,f'{task}.Scheduler.{key}')
                                       for key in ['Enable','Sensitive']}
                                for task in profile['pause_monthly_tasks']}}
    return result


def apply_source(root):
    """新版本只接受补丁上下文完全匹配；冲突留给 AI 逐项核查。"""
    assert_stopped(root)
    patch = HERE / 'upstream-local.patch'
    git = shutil.which('git')
    if not git:
        raise RuntimeError('找不到 Git。')
    flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}
    command = [git, '-C', str(root), 'apply', '--whitespace=nowarn']
    check = subprocess.run(command + ['--check', str(patch)], capture_output=True, text=True,
                           encoding='utf-8', errors='replace', **flags)
    if check.returncode:
        reverse = subprocess.run(command + ['--reverse', '--check', str(patch)],
                                 capture_output=True, **flags)
        if reverse.returncode == 0:
            return {'source_patch': 'already_applied', 'game_started': False}
        raise RuntimeError('新版补丁上下文已改变，未修改源码；请按维护清单人工迁移。\n' + check.stderr[:1500])
    subprocess.run(command + [str(patch)], check=True, **flags)
    return {'source_patch': 'applied', 'frontend_build_required': True, 'game_started': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['check', 'backup', 'apply', 'apply-source'])
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--config', default='alas2')
    parser.add_argument('--pause-monthly', action='store_true',
                        help='暂停每月开荒、侵蚀1和智能调度，并开启敏感任务保护')
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.action == 'check':
            result = audit(root, args.config)
        elif args.action == 'backup':
            result = {'private_backup': str(backup(root))}
        elif args.action == 'apply-source':
            result = apply_source(root)
        else:
            result = restore(root, args.config, args.pause_monthly)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.action == 'check':
            return 0 if result['configuration_matches'] and all(result['repair_hashes'].values()) else 1
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'[维护失败] {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
