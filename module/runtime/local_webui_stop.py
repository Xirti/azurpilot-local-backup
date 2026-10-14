"""固定启动入口通过本机命名事件请求 Uvicorn 正常退出。"""

import os
import re
import sys
import threading


EVENT_ENV = 'AZURPILOT_LOCAL_STOP_EVENT'
EVENT_PATTERN = r'Local\\AzurPilot-WebUI-[0-9a-f]{32}'


def event_name_is_valid(name: str) -> bool:
    return re.fullmatch(EVENT_PATTERN, name) is not None


def windows_events():
    """声明句柄宽度，避免 64 位 Windows 上截断命名事件句柄。"""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateEventW.restype = wintypes.HANDLE
    kernel.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.OpenEventW.restype = wintypes.HANDLE
    kernel.SetEvent.argtypes = [wintypes.HANDLE]
    kernel.SetEvent.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


def watch_shutdown(server):
    """仅固定 Windows 入口启用；触发后走 ASGI 原有资源清理流程。"""
    name = os.environ.get(EVENT_ENV, '')
    if sys.platform != 'win32' or not event_name_is_valid(name):
        return None
    import ctypes
    kernel = windows_events()
    handle = kernel.CreateEventW(None, False, False, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())

    def monitor():
        try:
            while not server.should_exit:
                result = kernel.WaitForSingleObject(handle, 500)
                if result == 0:
                    server.should_exit = True
                    return
                if result != 258:
                    return
        finally:
            kernel.CloseHandle(handle)

    thread = threading.Thread(target=monitor, name='local-webui-stop', daemon=True)
    thread.start()
    return thread


def signal_shutdown(name: str):
    """只触发已有事件，不创建新事件，不按进程名批量终止。"""
    if sys.platform != 'win32' or not event_name_is_valid(name):
        raise RuntimeError('本地关闭通道无效。')
    import ctypes
    kernel = windows_events()
    handle = kernel.OpenEventW(0x0002, False, name)
    if not handle:
        raise RuntimeError('本地关闭通道不存在，请用新版固定入口启动 WebUI。')
    try:
        if not kernel.SetEvent(handle):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(handle)


def shutdown_available() -> bool:
    """只为固定本地入口启动的 Windows 服务提供关闭能力。"""
    return sys.platform == 'win32' and event_name_is_valid(os.environ.get(EVENT_ENV, ''))


def request_webui_shutdown(confirm: bool) -> dict:
    """先验证当前服务通道，延后通知退出，为 API 响应留出发送时间。"""
    from module.api.protocol import ApiError
    if not confirm:
        raise ApiError('CONFIRM_REQUIRED', '请确认关闭后台；正在运行的任务将停止。')
    if not shutdown_available():
        raise ApiError('UNAVAILABLE', '此服务没有本地关闭通道，请使用本地启动器重新启动。')
    name = os.environ[EVENT_ENV]
    import ctypes
    kernel = windows_events()
    handle = kernel.OpenEventW(0x0002, False, name)
    if not handle:
        raise ApiError('UNAVAILABLE', '关闭通道不存在，未执行关闭。')
    # 保持已验证事件的句柄，禁止前端提供事件名或 PID。
    def notify():
        try:
            kernel.SetEvent(handle)
        finally:
            kernel.CloseHandle(handle)
    timer = threading.Timer(1.0, notify)
    timer.daemon = True
    timer.start()
    return {'accepted': True}
