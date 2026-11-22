import asyncio
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from threading import Thread
from time import monotonic
from tkinter import ttk

import psutil
from PIL import Image, ImageTk
from pypixelcolor import AsyncClient

from panel_preferences import SavedPanel, settings_file
from pc_status import (
    COLON_PHASE_MS,
    PANEL_BRIGHTNESS,
    PANEL_SIZE,
    REFRESH_INTERVAL,
    encode_status_animation,
    find_panels,
    read_status,
    render_status,
)
from windows_tray import TrayIcon

BACKGROUND = "#0e1522"
SURFACE = "#182335"
TEXT = "#f1f6fd"
MUTED = "#aec0d6"
ACCENT = "#7addfb"
BUTTON = "#30425a"
PREVIEW_SIZE = (512, 128)
ICON_PATH = Path(__file__).with_name("led-panel.ico")
RECONNECT_DELAY = 10


class PanelConnection:
    def __init__(self):
        self.panel = None

    async def connect(self, address):
        panel = AsyncClient(address)
        await panel.connect()
        self.panel = panel
        info = panel.get_device_info()
        if (info.width, info.height) != PANEL_SIZE:
            await self.disconnect()
            raise RuntimeError(f"Panel má {info.width} × {info.height} px. Aplikace podporuje 64 × 16 px.")

    async def disconnect(self):
        if self.panel is not None:
            panel, self.panel = self.panel, None
            await panel.disconnect()

    async def set_power(self, on):
        if on:
            await self.panel.set_brightness(PANEL_BRIGHTNESS)
        await self.panel.set_power(on)
        if on:
            psutil.cpu_percent()
            await asyncio.sleep(0.5)
            return await self.refresh()
        return None

    async def refresh(self):
        status = read_status()
        await self.panel.send_image_hex(encode_status_animation(*status), ".gif", save_slot=0)
        return status

    async def verify_connection(self):
        self.panel.get_device_info()


class PanelWindow:
    def __init__(self, root):
        self.root = root
        self.settings_path = settings_file()
        self.saved_panel = SavedPanel.load(self.settings_path)
        self.target_panel = self.saved_panel
        self.settings_error = False
        self.connection = PanelConnection()
        self.loop = asyncio.new_event_loop()
        Thread(target=self.loop.run_forever, daemon=True).start()
        self.pending = None
        self.devices = []
        self.connected = False
        self.powered = None
        self.snapshot = None
        self.preview_key = None
        self.photo = None
        self.next_refresh = 0.0
        self.retry_at = 0.0
        self.closing = False

        root.title("LED panel pro PC 1.1")
        root.iconbitmap(default=str(ICON_PATH))
        root.configure(bg=BACKGROUND)
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.hide_window)
        main = tk.Frame(root, bg=BACKGROUND, padx=24, pady=20)
        main.pack(fill="both", expand=True)
        self.label(main, "LED panel pro PC", size=22, bold=True, bg=BACKGROUND).pack(anchor="w")
        self.label(main, "Ovládání přes Bluetooth", color=MUTED, bg=BACKGROUND).pack(anchor="w", pady=(0, 16))

        connection_card = tk.Frame(main, bg=SURFACE, padx=16, pady=13)
        connection_card.pack(fill="x")
        self.label(connection_card, "Bluetooth zařízení", bold=True).pack(anchor="w")
        device_row = tk.Frame(connection_card, bg=SURFACE)
        device_row.pack(fill="x", pady=(7, 8))
        self.device = ttk.Combobox(device_row, state="disabled", font=("Segoe UI", 10))
        self.device.pack(side="left", fill="x", expand=True, ipady=4)
        self.scan_button = self.button(device_row, "Vyhledat", self.scan)
        self.scan_button.pack(side="left", padx=(8, 0))
        self.connect_button = self.button(device_row, "Připojit", self.toggle_connection)
        self.connect_button.pack(side="left", padx=(8, 0))
        self.message = self.label(connection_card, "Připraveno k vyhledání panelu.", color=MUTED)
        self.message.configure(wraplength=500, justify="left")
        self.message.pack(anchor="w")

        preview_card = tk.Frame(main, bg=SURFACE, padx=16, pady=13)
        preview_card.pack(fill="x", pady=(12, 0))
        heading = tk.Frame(preview_card, bg=SURFACE)
        heading.pack(fill="x", pady=(0, 9))
        self.label(heading, "Náhled panelu", bold=True).pack(side="left")
        self.label(heading, f"Obnova každých {REFRESH_INTERVAL} s", color=MUTED, size=9).pack(side="right")
        self.preview = tk.Canvas(preview_card, width=PREVIEW_SIZE[0], height=PREVIEW_SIZE[1], bg="#080d16", highlightthickness=0)
        self.preview.pack()
        self.preview_image = self.preview.create_image(0, 0, anchor="nw")
        self.preview_text = self.preview.create_text(
            PREVIEW_SIZE[0] // 2, PREVIEW_SIZE[1] // 2, fill=MUTED, font=("Segoe UI", 11)
        )

        power_row = tk.Frame(main, bg=BACKGROUND)
        power_row.pack(fill="x", pady=(16, 0))
        self.label(power_row, "Napájení displeje", bold=True, bg=BACKGROUND).pack(side="left")
        self.on_button = self.button(power_row, "Zapnout", lambda: self.set_power(True), primary=True)
        self.off_button = self.button(power_row, "Vypnout", lambda: self.set_power(False))
        self.off_button.pack(side="right")
        self.on_button.pack(side="right", padx=(0, 8))

        self.tray = TrayIcon(root, ICON_PATH, self.show_window, self.tray_actions)
        if self.saved_panel:
            self.set_devices([(self.saved_panel.name, self.saved_panel.address, 0)])
        else:
            root.after(150, self.scan)
        self.update_controls()
        root.after(80, self.tick)

    @staticmethod
    def label(parent, text, *, size=10, color=TEXT, bold=False, bg=SURFACE):
        return tk.Label(parent, text=text, bg=bg, fg=color, font=("Segoe UI", size, "bold" if bold else "normal"))

    @staticmethod
    def button(parent, text, command, *, primary=False):
        return tk.Button(
            parent, text=text, command=command, bg=ACCENT if primary else BUTTON,
            fg=BACKGROUND if primary else TEXT, activebackground="#b9edfc" if primary else "#465d77",
            activeforeground=BACKGROUND if primary else TEXT, disabledforeground="#a1b0c2",
            font=("Segoe UI", 10, "bold"), relief="flat", padx=13, pady=5,
            highlightthickness=1, highlightbackground=parent["bg"], highlightcolor=ACCENT,
        )

    def update_controls(self):
        ready = self.pending is None
        self.device.configure(state="readonly" if ready and self.devices and not self.connected else "disabled")
        self.scan_button.configure(state="normal" if ready and not self.connected else "disabled")
        connecting = self.target_panel is not None and not self.connected
        connection_label = "Odpojit" if self.connected else "Zrušit pokusy" if connecting else "Připojit"
        self.connect_button.configure(
            text=connection_label,
            state="normal" if ready and (self.connected or connecting or self.devices) else "disabled",
        )
        self.on_button.configure(state="normal" if self.can_set_power(True) else "disabled")
        self.off_button.configure(state="normal" if self.can_set_power(False) else "disabled")
        status = {True: "zapnuto", False: "vypnuto", None: "připojeno"}[self.powered] if self.connected else "odpojeno"
        self.tray.set_tooltip(status)

    def can_set_power(self, on):
        return self.pending is None and self.connected and self.powered is not on

    def tray_actions(self):
        return (
            ("Otevřít aplikaci", self.show_window),
            ("Zapnout panel", (lambda: self.set_power(True)) if self.can_set_power(True) else None),
            ("Vypnout panel", (lambda: self.set_power(False)) if self.can_set_power(False) else None),
            (None, None),
            ("Ukončit", self.close),
        )

    def submit(self, coroutine, callback):
        self.pending = asyncio.run_coroutine_threadsafe(coroutine, self.loop), callback
        self.update_controls()

    def scan(self):
        if self.closing or self.pending is not None or self.connected:
            return
        self.target_panel = None
        self.message.configure(text="Vyhledávám LED panely v okolí…", fg=MUTED)
        self.submit(find_panels(), self.scanned)

    def set_devices(self, devices):
        self.devices = devices
        self.device.configure(values=[f"{name}  ·  {address}" for name, address, _ in devices])
        if devices:
            self.device.current(0)
        else:
            self.device.set("")

    def scanned(self, devices):
        self.set_devices(devices)
        if devices:
            text = "Vyber svůj panel a klikni na Připojit."
        else:
            text = "Panel se nenašel. Zkontroluj napájení, Bluetooth a zavři aplikaci iPixel Color."
        self.message.configure(text=text, fg=MUTED)

    def toggle_connection(self):
        if self.pending is not None:
            return
        if self.connected:
            self.target_panel = None
            self.message.configure(text="Odpojuji panel…", fg=MUTED)
            self.submit(self.connection.disconnect(), self.disconnected)
        elif self.target_panel is not None:
            self.target_panel = None
            self.disconnected(None)
            self.update_controls()
        else:
            selected = self.device.current()
            if selected >= 0:
                name, address, _ = self.devices[selected]
                previous = self.saved_panel
                self.target_panel = SavedPanel(name, address, previous.powered if previous and previous.address == address else None)
                self.connect()

    def connect(self):
        panel = self.target_panel
        self.message.configure(text=f"Připojuji {panel.name}…", fg=MUTED)
        self.submit(self.connection.connect(panel.address), self.on_connected)

    def remember_panel(self):
        panel = self.target_panel
        if panel != self.saved_panel or self.settings_error:
            self.saved_panel = panel
            try:
                panel.save(self.settings_path)
                self.settings_error = False
            except OSError:
                self.settings_error = True

    def on_connected(self, _):
        self.connected = True
        self.remember_panel()
        self.refreshed(None)
        if self.target_panel.powered is None:
            self.connection_message("Připojeno. Zvol Zapnout nebo Vypnout.")
        else:
            self.set_power(self.target_panel.powered)

    def connection_message(self, text):
        if self.settings_error:
            text += " Nastavení se nepodařilo uložit."
        self.message.configure(text=text, fg=ACCENT)

    def disconnected(self, _):
        self.connected = False
        self.powered = self.snapshot = None
        self.message.configure(text="Panel je odpojený.", fg=MUTED)

    def set_power(self, on):
        if not self.can_set_power(on):
            return
        self.target_panel = replace(self.target_panel, powered=on)
        self.remember_panel()
        self.message.configure(text="Zapínám panel…" if on else "Vypínám panel…", fg=MUTED)
        self.submit(self.connection.set_power(on), lambda snapshot: self.power_changed(on, snapshot))

    def power_changed(self, on, snapshot):
        self.powered = on
        self.refreshed(snapshot)
        self.connection_message("Panel je zapnutý. Zobrazuje stav PC." if on else "Panel je vypnutý.")

    def refreshed(self, snapshot):
        self.snapshot = snapshot
        self.next_refresh = monotonic() + REFRESH_INTERVAL

    def tick(self):
        if self.closing:
            return
        if self.pending is not None and self.pending[0].done():
            future, callback = self.pending
            self.pending = None
            try:
                callback(future.result())
            except Exception as error:
                self.retry_at = monotonic() + RECONNECT_DELAY
                self.disconnected(None)
                retry = f" Další pokus za {RECONNECT_DELAY} s." if self.target_panel else ""
                self.message.configure(text=f"Bluetooth: {error}.{retry}", fg="#ffb6ac")
                self.submit(self.connection.disconnect(), lambda _: None)
            self.update_controls()

        now = monotonic()
        if self.pending is None:
            if self.connected and now >= self.next_refresh:
                poll = self.connection.refresh if self.powered else self.connection.verify_connection
                self.submit(poll(), self.refreshed)
            elif not self.connected and self.target_panel is not None and now >= self.retry_at:
                self.connect()
        if self.root.state() != "withdrawn":
            self.update_preview(now)
        self.root.after(80, self.tick)

    def update_preview(self, now):
        colon = int(now * 1000 / COLON_PHASE_MS) % 2 == 0
        key = (self.snapshot, colon if self.snapshot else None, self.powered)
        if key == self.preview_key:
            return
        self.preview_key = key
        if self.snapshot:
            frame = render_status(*self.snapshot, show_colon=colon)
            self.photo = ImageTk.PhotoImage(frame.resize(PREVIEW_SIZE, Image.Resampling.NEAREST))
            self.preview.itemconfigure(self.preview_image, image=self.photo)
            self.preview.itemconfigure(self.preview_text, text="")
        else:
            self.preview.itemconfigure(self.preview_image, image="")
            self.photo = None
            text = "Displej je vypnutý" if self.powered is False else "Živý náhled se zobrazí po zapnutí"
            self.preview.itemconfigure(self.preview_text, text=text)

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide_window(self):
        if self.tray.available:
            self.root.withdraw()
        else:
            self.close()

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.tray.close()
        self.root.withdraw()
        if self.pending is not None:
            self.pending[0].cancel()
            self.pending = None
        closed = asyncio.run_coroutine_threadsafe(self.connection.disconnect(), self.loop)

        def finish():
            if closed.done():
                self.loop.call_soon_threadsafe(self.loop.stop)
                self.root.destroy()
            else:
                self.root.after(60, finish)

        finish()


if __name__ == "__main__" and not TrayIcon.open_existing():
    window = tk.Tk()
    PanelWindow(window)
    window.mainloop()
