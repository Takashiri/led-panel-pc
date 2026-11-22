"""Windows notification area icon and its native context menu."""

import ctypes as ct
from ctypes import wintypes as win


WINDOW_NAME = "LED Panel pro PC - notification area"
TRAY_MESSAGE = 0x8001  # WM_APP + 1
OPEN_MESSAGE = 0x8002
WM_CONTEXTMENU = 0x007B
WM_HOTKEY = 0x0312
MODIFIERS = {"Ctrl": 0x0002, "Alt": 0x0001, "Shift": 0x0004}
MOD_NOREPEAT = 0x4000
HOTKEY_KEYS = {chr(code): code for code in (*range(48, 58), *range(65, 91))}
HOTKEY_KEYS.update({f"F{number}": 0x6F + number for number in range(1, 25) if number != 12})
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
NIN_SELECT = 0x0400
NIN_KEYSELECT = 0x0401
NIM_ADD, NIM_MODIFY, NIM_DELETE, NIM_SETFOCUS, NIM_SETVERSION = range(5)
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_SHOWTIP = 1, 2, 4, 0x80
NOTIFYICON_VERSION_4 = 4
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
MF_GRAYED, MF_SEPARATOR = 1, 0x0800
TPM_RIGHTBUTTON, TPM_RETURNCMD = 2, 0x0100

LRESULT = ct.c_ssize_t
UINT_PTR = ct.c_size_t
SUBCLASSPROC = ct.WINFUNCTYPE(
    LRESULT, win.HWND, win.UINT, win.WPARAM, win.LPARAM, UINT_PTR, UINT_PTR
)


class NotifyIconData(ct.Structure):
    _fields_ = [
        ("cbSize", win.DWORD),
        ("hWnd", win.HWND),
        ("uID", win.UINT),
        ("uFlags", win.UINT),
        ("uCallbackMessage", win.UINT),
        ("hIcon", win.HICON),
        ("szTip", win.WCHAR * 128),
        ("dwState", win.DWORD),
        ("dwStateMask", win.DWORD),
        ("szInfo", win.WCHAR * 256),
        ("uVersion", win.UINT),
        ("szInfoTitle", win.WCHAR * 64),
        ("dwInfoFlags", win.DWORD),
        ("guidItem", ct.c_ubyte * 16),
        ("hBalloonIcon", win.HICON),
    ]


def api(dll, name, result, *arguments):
    function = getattr(dll, name)
    function.restype = result
    function.argtypes = arguments
    return function


def parse_hotkey(text):
    if not text.strip():
        return "", 0, 0
    *parts, key = (part.strip().title() for part in text.split("+"))
    key = key.upper()
    if not parts or len(parts) != len(set(parts)) or set(parts) - MODIFIERS.keys() or key not in HOTKEY_KEYS:
        raise ValueError("Použij např. Ctrl+Alt+F9. Klávesa může být A–Z, 0–9 nebo F1–F24 kromě F12.")
    canonical = "+".join([*(name for name in MODIFIERS if name in parts), key])
    return canonical, sum(MODIFIERS[name] for name in parts), HOTKEY_KEYS[key]


user = ct.WinDLL("user32", use_last_error=True)
shell = ct.WinDLL("shell32", use_last_error=True)
controls = ct.WinDLL("comctl32", use_last_error=True)

create_window = api(user, "CreateWindowExW", win.HWND, win.DWORD, win.LPCWSTR, win.LPCWSTR,
                    win.DWORD, ct.c_int, ct.c_int, ct.c_int, ct.c_int, win.HWND,
                    win.HMENU, win.HINSTANCE, win.LPVOID)
find_window = api(user, "FindWindowW", win.HWND, win.LPCWSTR, win.LPCWSTR)
destroy_window = api(user, "DestroyWindow", win.BOOL, win.HWND)
post_message = api(user, "PostMessageW", win.BOOL, win.HWND, win.UINT, win.WPARAM, win.LPARAM)
register_message = api(user, "RegisterWindowMessageW", win.UINT, win.LPCWSTR)
register_hotkey = api(user, "RegisterHotKey", win.BOOL, win.HWND, ct.c_int, win.UINT, win.UINT)
unregister_hotkey = api(user, "UnregisterHotKey", win.BOOL, win.HWND, ct.c_int)
load_image = api(user, "LoadImageW", win.HANDLE, win.HINSTANCE, win.LPCWSTR,
                 win.UINT, ct.c_int, ct.c_int, win.UINT)
destroy_icon = api(user, "DestroyIcon", win.BOOL, win.HICON)
create_menu = api(user, "CreatePopupMenu", win.HMENU)
append_menu = api(user, "AppendMenuW", win.BOOL, win.HMENU, win.UINT, UINT_PTR, win.LPCWSTR)
destroy_menu = api(user, "DestroyMenu", win.BOOL, win.HMENU)
set_foreground = api(user, "SetForegroundWindow", win.BOOL, win.HWND)
cursor_position = api(user, "GetCursorPos", win.BOOL, ct.POINTER(win.POINT))
track_menu = api(user, "TrackPopupMenu", win.UINT, win.HMENU, win.UINT, ct.c_int, ct.c_int,
                 ct.c_int, win.HWND, ct.POINTER(win.RECT))
notify_icon = api(shell, "Shell_NotifyIconW", win.BOOL, win.DWORD, ct.POINTER(NotifyIconData))
set_subclass = api(controls, "SetWindowSubclass", win.BOOL, win.HWND, SUBCLASSPROC, UINT_PTR, UINT_PTR)
remove_subclass = api(controls, "RemoveWindowSubclass", win.BOOL, win.HWND, SUBCLASSPROC, UINT_PTR)
default_subclass = api(controls, "DefSubclassProc", LRESULT, win.HWND, win.UINT, win.WPARAM, win.LPARAM)


class TrayIcon:
    @staticmethod
    def open_existing():
        handle = find_window("Static", WINDOW_NAME)
        return bool(handle and post_message(handle, OPEN_MESSAGE, 0, 0))

    def __init__(self, root, icon_path, show_window, actions, next_page):
        self.root = root
        self.show_window = show_window
        self.actions = actions
        self.next_page = next_page
        self.hotkey_id = None
        self.hotkey = ""
        self.available = False
        self.menu_open = False
        self.modern_notifications = False
        self.taskbar_created = register_message("TaskbarCreated")
        self.callback = SUBCLASSPROC(self.window_proc)
        self.handle = create_window(0, "Static", WINDOW_NAME, 0, 0, 0, 0, 0, None, None, None, None)
        self.icon = load_image(None, str(icon_path), IMAGE_ICON, 16, 16, LR_LOADFROMFILE)

        self.data = NotifyIconData()
        self.data.cbSize = ct.sizeof(self.data)
        self.data.hWnd = self.handle
        self.data.uID = 1
        self.data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP
        self.data.uCallbackMessage = TRAY_MESSAGE
        self.data.hIcon = self.icon
        self.data.szTip = "LED panel pro PC"

        if self.handle and self.icon and set_subclass(self.handle, self.callback, 1, 0):
            self.add_icon()
        else:
            self.close()

    def add_icon(self):
        self.available = bool(notify_icon(NIM_ADD, ct.byref(self.data)))
        if self.available:
            self.data.uVersion = NOTIFYICON_VERSION_4
            self.modern_notifications = bool(notify_icon(NIM_SETVERSION, ct.byref(self.data)))

    def set_tooltip(self, text):
        tooltip = f"LED panel pro PC — {text}"[:127]
        if self.available and self.data.szTip != tooltip:
            self.data.szTip = tooltip
            notify_icon(NIM_MODIFY, ct.byref(self.data))

    def set_hotkey(self, text):
        canonical, modifiers, key = parse_hotkey(text)
        if canonical == self.hotkey:
            return canonical
        if not self.handle:
            raise ValueError("Windows nepřipravil příjem globální zkratky.")
        old = self.hotkey_id
        candidate = None
        if key:
            candidate = 3 if old == 2 else 2
            if not register_hotkey(self.handle, candidate, modifiers | MOD_NOREPEAT, key):
                raise ValueError("Tuto zkratku už používá Windows nebo jiná aplikace.")
        if old is not None:
            unregister_hotkey(self.handle, old)
        self.hotkey_id, self.hotkey = candidate, canonical
        return canonical

    def window_proc(self, handle, message, wparam, lparam, _subclass_id, _reference):
        if message == self.taskbar_created:
            self.add_icon()
            return 0
        if message == OPEN_MESSAGE:
            self.root.after_idle(self.show_window)
            return 0
        if message == WM_HOTKEY and wparam == self.hotkey_id:
            self.root.after_idle(self.next_page)
            return 0
        if message == TRAY_MESSAGE:
            event = lparam & 0xFFFF
            menu_event = WM_CONTEXTMENU if self.modern_notifications else WM_RBUTTONUP
            if event == menu_event:
                self.root.after_idle(self.show_menu)
            elif event in (NIN_SELECT, NIN_KEYSELECT) or (not self.modern_notifications and event == WM_LBUTTONUP):
                self.root.after_idle(self.show_window)
            return 0
        return default_subclass(handle, message, wparam, lparam)

    def show_menu(self):
        if self.menu_open or not self.handle:
            return
        menu = create_menu()
        if not menu:
            return
        self.menu_open = True
        selection = 0
        actions = {}
        try:
            for index, (label, action) in enumerate(self.actions(), start=1):
                flags = MF_SEPARATOR if label is None else (MF_GRAYED if action is None else 0)
                append_menu(menu, flags, index, label)
                if action is not None:
                    actions[index] = action
            point = win.POINT()
            cursor_position(ct.byref(point))
            set_foreground(self.handle)
            selection = track_menu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD, point.x, point.y, 0, self.handle, None)
            post_message(self.handle, 0, 0, 0)  # WM_NULL completes menu dismissal.
            notify_icon(NIM_SETFOCUS, ct.byref(self.data))
        finally:
            destroy_menu(menu)
            self.menu_open = False
        if selection in actions:
            actions[selection]()

    def close(self):
        if self.available:
            notify_icon(NIM_DELETE, ct.byref(self.data))
            self.available = False
        if self.handle:
            if self.hotkey_id is not None:
                unregister_hotkey(self.handle, self.hotkey_id)
            remove_subclass(self.handle, self.callback, 1)
            destroy_window(self.handle)
            self.handle = None
        if self.icon:
            destroy_icon(self.icon)
            self.icon = None
