"""Windows notification area icon and its native context menu."""

import ctypes as ct
from ctypes import wintypes as win


WINDOW_NAME = "LED Panel pro PC - notification area"
TRAY_MESSAGE = 0x8001  # WM_APP + 1
OPEN_MESSAGE = 0x8002
WM_CONTEXTMENU = 0x007B
WM_HOTKEY = 0x0312
MODIFIERS = {"Ctrl": 0x0002, "Alt": 0x0001, "Shift": 0x0004}
MODIFIER_KEYS = {0x11: MODIFIERS["Ctrl"], 0x12: MODIFIERS["Alt"], 0x10: MODIFIERS["Shift"],
                 0x5B: 0x0008, 0x5C: 0x0008}
CHARACTER_MODIFIERS = {1: MODIFIERS["Shift"], 2: MODIFIERS["Ctrl"], 4: MODIFIERS["Alt"]}
MOD_NOREPEAT = 0x4000
CHORD_POLL_MS = 20
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
        return "", 0, ()
    modifiers = []
    keys = []
    for part in (part.strip() for part in text.split("+")):
        if part.title() in MODIFIERS:
            modifiers.append(part.title())
        else:
            keys.append(part.upper() if part.upper() in HOTKEY_KEYS else part)
    valid_single = len(keys) == 1 and modifiers and keys[0] in HOTKEY_KEYS
    valid_pair = len(keys) == 2 and keys[0] != keys[1] and all(
        key in HOTKEY_KEYS or (len(key) == 1 and key.isprintable() and ord(key) <= 0xFFFF) for key in keys
    )
    if len(modifiers) != len(set(modifiers)) or not (valid_single or valid_pair):
        raise ValueError("Použij např. Ctrl+Alt+F9 nebo dvě různé klávesy jako §+).")
    canonical = "+".join([*(name for name in MODIFIERS if name in modifiers), *keys])
    return canonical, sum(MODIFIERS[name] for name in modifiers), tuple(keys)


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
get_foreground_window = api(user, "GetForegroundWindow", win.HWND)
get_window_thread = api(user, "GetWindowThreadProcessId", win.DWORD, win.HWND, ct.POINTER(win.DWORD))
get_keyboard_layout = api(user, "GetKeyboardLayout", win.HANDLE, win.DWORD)
key_for_character = api(user, "VkKeyScanExW", ct.c_short, win.WCHAR, win.HANDLE)
async_key_state = api(user, "GetAsyncKeyState", ct.c_short, ct.c_int)
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


def resolve_chord(keys, modifiers, layout):
    codes = []
    for key in keys:
        code = HOTKEY_KEYS.get(key)
        if code is None:
            mapping = key_for_character(key, layout)
            if not 0 <= mapping <= 0x07FF:
                return None
            for flag, modifier in CHARACTER_MODIFIERS.items():
                if mapping >> 8 & flag:
                    modifiers |= modifier
            code = mapping & 0xFF
        codes.append(code)
    return (tuple(codes), modifiers) if codes[0] != codes[1] else None


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
        self.chord = None
        self.chord_timer = None
        self.chord_layout = None
        self.chord_keys = None
        self.chord_pressed = False
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

    def set_hotkey(self, text, *, validate_chord=True):
        canonical, modifiers, keys = parse_hotkey(text)
        if canonical == self.hotkey:
            return canonical
        if not self.handle:
            raise ValueError("Windows nepřipravil příjem globální zkratky.")
        old = self.hotkey_id
        candidate = None
        chord = None
        if len(keys) == 1:
            candidate = 3 if old == 2 else 2
            if not register_hotkey(self.handle, candidate, modifiers | MOD_NOREPEAT, HOTKEY_KEYS[keys[0]]):
                raise ValueError("Tuto zkratku už používá Windows nebo jiná aplikace.")
        elif len(keys) == 2:
            if validate_chord and resolve_chord(keys, modifiers, get_keyboard_layout(0)) is None:
                raise ValueError("Zkratku nelze na aktuálním rozložení stisknout jako dvě různé klávesy.")
            chord = keys, modifiers
        if old is not None:
            unregister_hotkey(self.handle, old)
        self.hotkey_id, self.hotkey = candidate, canonical
        self.stop_chord()
        self.chord = chord
        if chord is not None:
            self.chord_layout = None
            self.chord_timer = self.root.after(CHORD_POLL_MS, self.poll_chord)
        return canonical

    def poll_chord(self):
        keys, modifiers = self.chord
        foreground = get_foreground_window()
        layout = get_keyboard_layout(get_window_thread(foreground, None) if foreground else 0)
        if layout != self.chord_layout:
            self.chord_layout = layout
            self.chord_keys = resolve_chord(keys, modifiers, layout)

        pressed = False
        if self.chord_keys is not None:
            codes, expected = self.chord_keys
            if all(async_key_state(code) < 0 for code in codes):
                held = 0
                for code, flag in MODIFIER_KEYS.items():
                    if async_key_state(code) < 0:
                        held |= flag
                pressed = held == expected
        if pressed and not self.chord_pressed:
            self.root.after_idle(self.next_page)
        self.chord_pressed = pressed
        self.chord_timer = self.root.after(CHORD_POLL_MS, self.poll_chord)

    def stop_chord(self):
        if self.chord_timer is not None:
            self.root.after_cancel(self.chord_timer)
            self.chord_timer = None
        self.chord = self.chord_keys = None
        self.chord_pressed = False

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
        self.stop_chord()
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
