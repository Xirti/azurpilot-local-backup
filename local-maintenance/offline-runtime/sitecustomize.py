"""本地版默认限制 Python 标准网络连接到本机回环地址。"""
import errno
import ipaddress
import os
import socket

def _loopback(host):
    if isinstance(host, bytes):
        host = host.decode('ascii', 'strict')
    if str(host).lower().rstrip('.') == 'localhost':
        return True
    try:
        return ipaddress.ip_address(str(host).split('%')[0]).is_loopback
    except ValueError:
        return False

def _allow_address(sock, address):
    if sock.family == getattr(socket, 'AF_UNIX', object()):
        return
    if sock.family not in (socket.AF_INET, socket.AF_INET6) or not _loopback(address[0]):
        raise PermissionError(errno.EACCES, '本地模式禁止 Python 外网连接')

def install():
    if getattr(socket, '_azurpilot_local_guard', False):
        return
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_sendto = socket.socket.sendto
    original_getaddrinfo = socket.getaddrinfo
    def connect(sock, address):
        _allow_address(sock, address)
        return original_connect(sock, address)
    def connect_ex(sock, address):
        try:
            _allow_address(sock, address)
        except PermissionError:
            return errno.EACCES
        return original_connect_ex(sock, address)
    def sendto(sock, *args):
        _allow_address(sock, args[-1])
        return original_sendto(sock, *args)
    def getaddrinfo(host, *args, **kwargs):
        if host is not None and not _loopback(host):
            raise PermissionError(errno.EACCES, '本地模式禁止外部 DNS 查询')
        return original_getaddrinfo(host, *args, **kwargs)
    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.socket.sendto = sendto
    socket.getaddrinfo = getaddrinfo
    socket._azurpilot_local_guard = True

if os.environ.get('AZURPILOT_LOCAL_MODE') == '1':
    install()
