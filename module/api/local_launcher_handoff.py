"""本机首屏交接通知：只确认界面已呈现，不授予配置或进程控制权限。"""
import json
from pathlib import Path
import re
import time

import psutil
from starlette.responses import JSONResponse
from starlette.routing import Route

from module.api.socket import Gateway


def routes(root: Path):
    directory = root / 'cache/local-launcher/handoff'

    async def endpoint(request):
        if not Gateway.is_local(request):
            return JSONResponse({'error': '只允许本机直连'}, status_code=403)
        if request.method == 'GET':
            return JSONResponse({'protocol': 1})
        if request.headers.get('origin') != f'{request.url.scheme}://{request.url.netloc}':
            return JSONResponse({'error': '需要同源页面通知'}, status_code=403)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError('交接通知格式错误')
            ticket = body.get('ticket', '')
            stage = body.get('stage')
            if not isinstance(ticket, str) or not re.fullmatch(r'[0-9a-f]{32}', ticket) or stage not in ('ready', 'auth'):
                raise ValueError('交接通知格式错误')
            path = directory / (ticket + '.json')
            record = json.loads(path.read_text(encoding='utf-8'))
            if record.get('protocol') != 1 or not time.time() < record['expires_at'] <= time.time() + 120:
                raise ValueError('交接已过期')
            owner = psutil.Process(record['owner_pid'])
            if abs(owner.create_time() - record['owner_created_at']) > .05:
                raise ValueError('启动器身份已改变')
            if record.get('state') != 'waiting':
                raise ValueError('交接已完成')
            record.update(state='ready', stage=stage)
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(record), encoding='utf-8')
            temporary.replace(path)
            return JSONResponse({'accepted': True})
        except (ValueError, KeyError, TypeError, OSError, psutil.Error):
            return JSONResponse({'error': '交接通知无效或已过期'}, status_code=409)

    return [Route('/api/local-launcher/handoff', endpoint, methods=['GET', 'POST'])]
