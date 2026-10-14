"""在候选副本中调用上游配置与业务数据迁移，不启动调度器。"""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PRESERVED = ('CloseEmulatorDuringLongWait', 'WhenTaskQueueEmpty', 'WhenSchedulerStopped')


def migrate():
    from module.persistence.database import initialize
    from module.config.config_updater import ConfigUpdater
    from module.config.utils import write_file
    database = initialize()
    updater = ConfigUpdater()
    migrated = []
    for path in sorted(Path('config').glob('*.json')):
        if path.name.startswith('template'):
            continue
        old = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(old, dict) or not isinstance(old.get('Alas'), dict):
            continue
        values = {key: old['Alas']['Optimization'][key] for key in PRESERVED}
        new = updater.config_update(old)
        for key, value in values.items():
            if key not in new.get('Alas', {}).get('Optimization', {}):
                raise RuntimeError('新版已调整等待/队列/停止选项，需要先适配。')
            new['Alas']['Optimization'][key] = value
        write_file(str(path), new)
        migrated.append(path.stem)
    return {'database_created': database.path.is_file(), 'instances_migrated': len(migrated)}


if __name__ == '__main__':
    print(json.dumps(migrate(), ensure_ascii=False))
