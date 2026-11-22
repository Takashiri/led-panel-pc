import asyncio
import tkinter as tk
from threading import Thread
from time import monotonic
from tkinter import ttk

import psutil
from PIL import Image, ImageTk
from pypixelcolor import AsyncClient

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

BACKGROUND = "#0e1522"
SURFACE = "#182335"
TEXT = "#f1f6fd"
MUTED = "#aec0d6"
ACCENT = "#7addfb"
BUTTON = "#30425a"
PREVIEW_SIZE = (512, 128)


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


class PanelWindow:
    def __init__(self, root):
        self.root = root
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
        self.closing = False

        root.title("LED panel pro PC")
        root.configure(bg=BACKGROUND)
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.close)
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

        self.update_controls()
        root.after(150, self.scan)
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
        self.connect_button.configure(
            text="Odpojit" if self.connected else "Připojit",
            state="normal" if ready and (self.connected or self.devices) else "disabled",
        )
        self.on_button.configure(state="normal" if ready and self.connected and self.powered is not True else "disabled")
        self.off_button.configure(state="normal" if ready and self.connected and self.powered is not False else "disabled")

    def submit(self, coroutine, callback):
        self.pending = asyncio.run_coroutine_threadsafe(coroutine, self.loop), callback
        self.update_controls()

    def scan(self):
        if self.closing:
            return
        self.message.configure(text="Vyhledávám LED panely v okolí…", fg=MUTED)
        self.submit(find_panels(), self.scanned)

    def scanned(self, devices):
        self.devices = devices
        self.device.configure(values=[f"{name}  ·  {address}" for name, address, _ in devices])
        if devices:
            self.device.current(0)
            text = "Vyber svůj panel a klikni na Připojit."
        else:
            self.device.set("")
            text = "Panel se nenašel. Zkontroluj napájení, Bluetooth a zavři aplikaci iPixel Color."
        self.message.configure(text=text, fg=MUTED)

    def toggle_connection(self):
        if self.connected:
            self.message.configure(text="Odpojuji panel…", fg=MUTED)
            self.submit(self.connection.disconnect(), self.disconnected)
        else:
            name, address, _ = self.devices[self.device.current()]
            self.message.configure(text=f"Připojuji {name}…", fg=MUTED)
            self.submit(self.connection.connect(address), self.on_connected)

    def on_connected(self, _):
        self.connected = True
        self.message.configure(text="Připojeno. Zvol Zapnout nebo Vypnout.", fg=ACCENT)

    def disconnected(self, _):
        self.connected = False
        self.powered = self.snapshot = None
        self.message.configure(text="Panel je odpojený.", fg=MUTED)

    def set_power(self, on):
        self.message.configure(text="Zapínám panel…" if on else "Vypínám panel…", fg=MUTED)
        self.submit(self.connection.set_power(on), lambda snapshot: self.power_changed(on, snapshot))

    def power_changed(self, on, snapshot):
        self.powered = on
        self.refreshed(snapshot)
        self.message.configure(text="Panel je zapnutý. Zobrazuje stav PC." if on else "Panel je vypnutý.", fg=ACCENT)

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
                self.disconnected(None)
                self.message.configure(text=f"Bluetooth: {error}", fg="#ffb6ac")
                self.submit(self.connection.disconnect(), lambda _: None)
            self.update_controls()

        now = monotonic()
        if self.pending is None and self.powered and now >= self.next_refresh:
            self.submit(self.connection.refresh(), self.refreshed)
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

    def close(self):
        self.closing = True
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


if __name__ == "__main__":
    window = tk.Tk()
    PanelWindow(window)
    window.mainloop()
