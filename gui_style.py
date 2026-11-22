"""Shared dark theme and card layout for the Windows interface."""

import ctypes
import tkinter as tk
from ctypes import wintypes
from tkinter import ttk

from windows_tray import GA_ROOT, api, get_ancestor


BACKGROUND = "#10151e"
SURFACE = "#191f2b"
BORDER = "#303a4b"
FIELD = "#131923"
BUTTON = "#283344"
HOVER = "#35445a"
TEXT = "#f0f4fc"
MUTED = "#aab8cc"
ACCENT = "#83d9f6"
ACCENT_HOVER = "#ade8fa"
SELECTED = "#233b4d"
ERROR = "#ffada9"
FONT = ("Segoe UI", 10)
MEDIUM = ("Segoe UI", 10, "bold")


def configure_theme(root):
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=FONT, background=BACKGROUND, foreground=TEXT, bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER, focuscolor=ACCENT, troughcolor=FIELD)
    style.configure("TFrame", background=BACKGROUND)
    style.configure("Card.TFrame", background=SURFACE)
    style.configure("TLabel", background=BACKGROUND)
    style.configure("Title.TLabel", font=("Segoe UI", 23, "bold"))
    style.configure("Muted.TLabel", foreground=MUTED, font=("Segoe UI", 9))
    style.configure("Card.TLabel", background=SURFACE)
    style.configure("Heading.Card.TLabel", font=("Segoe UI", 12, "bold"))
    style.configure("Muted.Card.TLabel", foreground=MUTED, font=("Segoe UI", 9))

    style.configure("TNotebook", background=BACKGROUND, lightcolor=BACKGROUND, darkcolor=BACKGROUND,
                    bordercolor=BACKGROUND, borderwidth=0, padding=0, tabmargins=0)
    style.layout("TNotebook.Tab", [
        ("Notebook.tab", {"sticky": "nswe", "children": [
            ("Notebook.padding", {"sticky": "nswe", "children": [("Notebook.label", {"sticky": ""})]}),
        ]}),
    ])
    style.configure("TNotebook.Tab", padding=(19, 9), background=BACKGROUND, foreground=MUTED,
                    font=MEDIUM, borderwidth=1, lightcolor=BORDER, darkcolor=BORDER, bordercolor=BORDER)
    tab_focus = [("selected", "focus", "#55778c")]
    style.map("TNotebook.Tab", background=[("selected", SURFACE), ("active", BUTTON)],
              foreground=[("selected", ACCENT), ("active", TEXT)], padding=[],
              bordercolor=tab_focus, lightcolor=tab_focus, darkcolor=tab_focus)

    style.configure("TButton", background=BUTTON, foreground=TEXT, padding=(12, 7),
                    borderwidth=1, relief="flat", font=MEDIUM)
    style.map("TButton", background=[("disabled", SURFACE), ("pressed", SELECTED), ("active", HOVER)],
              foreground=[("disabled", MUTED)], bordercolor=[("focus", ACCENT)])
    style.configure("Primary.TButton", background=ACCENT, foreground=BACKGROUND,
                    bordercolor=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT, focuscolor=BACKGROUND)
    style.map("Primary.TButton", background=[("disabled", BUTTON), ("pressed", ACCENT_HOVER), ("active", ACCENT_HOVER)],
              foreground=[("disabled", MUTED)], bordercolor=[("disabled", BORDER), ("focus", TEXT)])
    style.configure("Screen.Toolbutton", padding=(10, 6), background=BUTTON, foreground=MUTED, borderwidth=1, font=MEDIUM)
    style.map("Screen.Toolbutton", background=[("selected", SELECTED), ("active", HOVER)],
              foreground=[("selected", ACCENT), ("active", TEXT)], bordercolor=[("focus", ACCENT), ("selected", SELECTED)])

    for field in ("TEntry", "TCombobox"):
        style.configure(field, fieldbackground=FIELD, background=BUTTON, foreground=TEXT,
                        arrowcolor=MUTED, insertcolor=TEXT, padding=(9, 6), selectbackground=SELECTED,
                        selectforeground=TEXT)
        style.map(field, fieldbackground=[("disabled", SURFACE), ("readonly", FIELD)],
                  foreground=[("disabled", MUTED)], bordercolor=[("focus", ACCENT)],
                  background=[("active", HOVER), ("readonly", BUTTON)])
    style.configure("TCheckbutton", background=SURFACE, indicatorbackground=FIELD,
                    indicatorforeground=BACKGROUND, padding=(0, 4))
    style.map("TCheckbutton", indicatorbackground=[("disabled", BUTTON), ("selected", ACCENT)],
              foreground=[("disabled", MUTED)], background=[("active", SURFACE)])
    style.configure("Vertical.TScrollbar", background=BUTTON, arrowcolor=MUTED)
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", SELECTED)
    root.option_add("*TCombobox*Listbox.selectForeground", TEXT)
    root.option_add("*TCombobox*Listbox.font", FONT)


def make_card(parent):
    border = tk.Frame(parent, background=BORDER, padx=1, pady=1)
    body = ttk.Frame(border, style="Card.TFrame", padding=(16, 13))
    body.pack(fill="both", expand=True)
    return border, body


def dark_caption(window):
    handle = get_ancestor(window.winfo_id(), GA_ROOT)
    if handle:
        set_attribute = api(ctypes.WinDLL("dwmapi"), "DwmSetWindowAttribute", ctypes.c_long,
                            wintypes.HWND, wintypes.DWORD, wintypes.LPCVOID, wintypes.DWORD)
        dark = wintypes.BOOL(True)
        set_attribute(handle, 20, ctypes.byref(dark), ctypes.sizeof(dark))  # DWMWA_USE_IMMERSIVE_DARK_MODE
