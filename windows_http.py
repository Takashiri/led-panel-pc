"""Small HTTPS reader using Windows' system proxy and certificate store."""

import ctypes as ct
from contextlib import ExitStack
from ctypes import wintypes as win
from urllib.parse import urlsplit, urlunsplit


AUTOMATIC_PROXY = 4
SECURE = 0x00800000
STATUS_CODE_AS_NUMBER = 19 | 0x20000000
TIMEOUT_MS = 6000
MAX_BODY = 1024 * 1024

http = ct.WinDLL("winhttp", use_last_error=True)


def bind(name, result, *arguments):
    function = getattr(http, name)
    function.restype = result
    function.argtypes = arguments
    return function


open_session = bind("WinHttpOpen", win.HANDLE, win.LPCWSTR, win.DWORD, win.LPCWSTR, win.LPCWSTR, win.DWORD)
set_timeouts = bind("WinHttpSetTimeouts", win.BOOL, win.HANDLE, ct.c_int, ct.c_int, ct.c_int, ct.c_int)
connect = bind("WinHttpConnect", win.HANDLE, win.HANDLE, win.LPCWSTR, ct.c_ushort, win.DWORD)
open_request = bind("WinHttpOpenRequest", win.HANDLE, win.HANDLE, win.LPCWSTR, win.LPCWSTR,
                    win.LPCWSTR, win.LPCWSTR, ct.POINTER(win.LPCWSTR), win.DWORD)
send_request = bind("WinHttpSendRequest", win.BOOL, win.HANDLE, win.LPCWSTR, win.DWORD,
                    win.LPVOID, win.DWORD, win.DWORD, ct.c_size_t)
receive_response = bind("WinHttpReceiveResponse", win.BOOL, win.HANDLE, win.LPVOID)
query_headers = bind("WinHttpQueryHeaders", win.BOOL, win.HANDLE, win.DWORD, win.LPCWSTR,
                     win.LPVOID, ct.POINTER(win.DWORD), ct.POINTER(win.DWORD))
read_data = bind("WinHttpReadData", win.BOOL, win.HANDLE, win.LPVOID, win.DWORD, ct.POINTER(win.DWORD))
close_handle = bind("WinHttpCloseHandle", win.BOOL, win.HANDLE)


def checked(result):
    if not result:
        raise ct.WinError(ct.get_last_error())
    return result


def open_handle(stack, handle):
    checked(handle)
    stack.callback(close_handle, handle)
    return handle


def get(url, user_agent, *, max_body=MAX_BODY):
    address = urlsplit(url)
    if address.scheme != "https" or not address.hostname or address.username or address.password:
        raise ValueError("Zdroj musí používat HTTPS.")
    path = urlunsplit(("", "", address.path or "/", address.query, ""))
    with ExitStack() as stack:
        session = open_handle(stack, open_session(user_agent, AUTOMATIC_PROXY, None, None, 0))
        checked(set_timeouts(session, TIMEOUT_MS, TIMEOUT_MS, TIMEOUT_MS, TIMEOUT_MS))
        connection = open_handle(stack, connect(session, address.hostname, address.port or 443, 0))
        accepted = (win.LPCWSTR * 2)("*/*", None)
        request = open_handle(stack, open_request(connection, "GET", path, None, None, accepted, SECURE))
        checked(send_request(request, None, 0, None, 0, 0, 0))
        checked(receive_response(request, None))
        code = win.DWORD()
        code_size = win.DWORD(ct.sizeof(code))
        checked(query_headers(request, STATUS_CODE_AS_NUMBER, None, ct.byref(code), ct.byref(code_size), None))
        if code.value != 200:
            raise OSError(f"Zdroj odpověděl stavem HTTP {code.value}.")

        body = bytearray()
        chunk = ct.create_string_buffer(8192)
        size = win.DWORD()
        while True:
            checked(read_data(request, chunk, ct.sizeof(chunk), ct.byref(size)))
            if not size.value:
                return bytes(body)
            body.extend(chunk.raw[:size.value])
            if len(body) > max_body:
                raise ValueError("Odpověď zdroje je příliš velká.")
