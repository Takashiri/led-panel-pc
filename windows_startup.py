"""Per-user Windows sign-in registration for the portable EXE."""

import winreg


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "LED Panel PC"
TRAY_ARGUMENT = "--start-in-tray"


def make_command(executable, hidden):
    command = f'"{executable}"'
    if hidden:
        command += f" {TRAY_ARGUMENT}"
    if len(command.encode("utf-16-le")) // 2 > 260:
        raise ValueError("Cesta k aplikaci je pro spuštění s Windows příliš dlouhá. Přesuň EXE do kratší cesty.")
    return command


def read_command():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            command, kind = winreg.QueryValueEx(key, VALUE_NAME)
    except FileNotFoundError:
        return None
    if kind != winreg.REG_SZ:
        raise OSError("Položka pro spuštění s Windows má neočekávaný typ.")
    return command


def write_command(command):
    if command is None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, access=winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, VALUE_NAME)
        except FileNotFoundError:
            pass
    else:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, access=winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
