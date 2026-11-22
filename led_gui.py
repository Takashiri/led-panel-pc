import asyncio
import sys
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from threading import Thread
from time import monotonic
from tkinter import messagebox, ttk

import psutil
from PIL import Image, ImageTk
from pypixelcolor import AsyncClient

from app_update import APP_VERSION, check_for_update, download_update, install_update
from display_pages import (
    NEWS_COLOR,
    NEWS_SPEED,
    Page,
    png_hex,
    read_headline,
    read_weather,
    render_news,
    render_weather,
    ticker_font,
)
from display_settings import DisplaySettingsWindow
from panel_preferences import DisplayPreferences, SavedPanel, settings_file
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
FETCH_INTERVALS = {Page.WEATHER: 900, Page.NEWS: 300}
FETCH_RETRY = 60
MAX_CONTENT_AGE = 3600
UPDATE_CHECK_INTERVAL = 24 * 60 * 60


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

    async def refresh(self, page, location, data, notice):
        if page is Page.PC:
            status = read_status()
            await self.panel.send_image_hex(encode_status_animation(*status), ".gif", save_slot=0)
            return status
        if page is Page.NEWS and data is not None:
            await self.panel.send_text(data.ticker, animation="scroll_left", speed=NEWS_SPEED,
                                       color=NEWS_COLOR, font=ticker_font(), save_slot=0)
        else:
            frame = render_weather(location, data, notice) if page is Page.WEATHER else render_news(None, notice)
            await self.panel.send_image_hex(png_hex(frame), ".png", save_slot=0)
        return None

    async def verify_connection(self):
        self.panel.get_device_info()


class PanelWindow:
    def __init__(self, root):
        self.root = root
        self.settings_path = settings_file()
        self.display_settings_path = self.settings_path.with_name("display.json")
        self.preferences = DisplayPreferences.load(self.display_settings_path)
        self.settings_dialog = None
        self.page = Page.PC
        self.sent_content = None
        self.content_cache = {}
        self.content_errors = {}
        self.content_jobs = {}
        self.next_fetch = {}
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
        self.update_job = None
        self.available_update = None
        self.next_update_check = monotonic() + 5

        root.title(f"LED panel pro PC {APP_VERSION}")
        root.iconbitmap(default=str(ICON_PATH))
        root.configure(bg=BACKGROUND)
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.hide_window)
        main = tk.Frame(root, bg=BACKGROUND, padx=24, pady=20)
        main.pack(fill="both", expand=True)
        header = tk.Frame(main, bg=BACKGROUND)
        header.pack(fill="x")
        self.label(header, "LED panel pro PC", size=22, bold=True, bg=BACKGROUND).pack(side="left")
        self.button(header, "Nastavení", self.open_settings).pack(side="right")
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
        self.page_choice = ttk.Combobox(heading, state="readonly", values=[page.value for page in Page], width=12)
        self.page_choice.set(self.page.value)
        self.page_choice.bind("<<ComboboxSelected>>", lambda _: self.select_page(Page(self.page_choice.get())))
        self.page_choice.pack(side="right")
        self.shortcut_hint = self.label(heading, "", color=MUTED, size=9)
        self.shortcut_hint.pack(side="right", padx=(0, 10))
        self.preview = tk.Canvas(preview_card, width=PREVIEW_SIZE[0], height=PREVIEW_SIZE[1], bg="#080d16", highlightthickness=0)
        self.preview.pack()
        self.preview_image = self.preview.create_image(0, 0, anchor="nw")
        self.preview_text = self.preview.create_text(
            PREVIEW_SIZE[0] // 2, PREVIEW_SIZE[1] // 2, fill=MUTED, font=("Segoe UI", 11)
        )
        self.preview_detail = self.label(preview_card, "", color=MUTED, size=9)
        self.preview_detail.configure(wraplength=512, justify="left")
        self.preview_detail.pack(fill="x", pady=(6, 0))

        power_row = tk.Frame(main, bg=BACKGROUND)
        power_row.pack(fill="x", pady=(16, 0))
        self.label(power_row, "Napájení displeje", bold=True, bg=BACKGROUND).pack(side="left")
        self.on_button = self.button(power_row, "Zapnout", lambda: self.set_power(True), primary=True)
        self.off_button = self.button(power_row, "Vypnout", lambda: self.set_power(False))
        self.off_button.pack(side="right")
        self.on_button.pack(side="right", padx=(0, 8))

        self.update_button = None
        if getattr(sys, "frozen", False):
            update_row = tk.Frame(main, bg=BACKGROUND)
            update_row.pack(fill="x", pady=(12, 0))
            self.update_button = self.button(update_row, "Zkontrolovat aktualizace", self.update_action)
            self.update_button.pack(side="right")
            self.update_status = self.label(update_row, f"Verze {APP_VERSION}", color=MUTED, bg=BACKGROUND)
            self.update_status.configure(wraplength=295, justify="left")
            self.update_status.pack(side="left")

        self.tray = TrayIcon(root, ICON_PATH, self.show_window, self.tray_actions, self.cycle_page)
        try:
            shortcut = self.tray.set_hotkey(self.preferences.hotkey, validate_chord=False)
        except ValueError:
            self.shortcut_hint.configure(text="Zkratka není aktivní")
        else:
            self.shortcut_hint.configure(text=shortcut)
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
            ("Další obrazovka", self.cycle_page),
            (None, None),
            ("Ukončit", self.close),
        )

    def submit(self, coroutine, callback):
        self.pending = asyncio.run_coroutine_threadsafe(coroutine, self.loop), callback
        self.update_controls()

    def online(self, function, *args):
        return asyncio.run_coroutine_threadsafe(asyncio.to_thread(function, *args), self.loop)

    def update_action(self):
        update = self.available_update
        if update is None:
            self.check_updates(manual=True)
        else:
            self.update_button.configure(state="disabled")
            self.update_status.configure(text=f"Stahuji verzi {update.version}…")
            self.update_job = self.online(download_update, update), self.finish_install

    def check_updates(self, *, manual):
        self.next_update_check = monotonic() + UPDATE_CHECK_INTERVAL
        self.update_button.configure(state="disabled")
        if manual:
            self.update_status.configure(text="Kontroluji vydání na GitHubu…")
        self.update_job = self.online(check_for_update), lambda job: self.finish_update_check(job, manual)

    def finish_update_check(self, job, manual):
        try:
            self.available_update = job.result()
        except (OSError, ValueError) as error:
            if manual:
                self.update_status.configure(text=f"Kontrola se nezdařila. {error}")
        else:
            if self.available_update:
                version = self.available_update.version
                self.update_status.configure(text=f"Dostupná verze {version}")
                self.update_button.configure(text="Nainstalovat a restartovat")
            else:
                text = f"Verze {APP_VERSION} je aktuální." if manual else f"Verze {APP_VERSION}"
                self.update_status.configure(text=text)
                self.update_button.configure(text="Zkontrolovat aktualizace")
        self.update_button.configure(state="normal")

    def finish_install(self, job):
        try:
            install_update(job.result())
        except (OSError, ValueError) as error:
            self.update_status.configure(text="Aktualizaci se nepodařilo nainstalovat.")
            self.update_button.configure(state="normal")
            self.show_window()
            messagebox.showerror("Aktualizace LED Panel PC", str(error), parent=self.root)
        else:
            self.close()

    def tick_update(self, now):
        if self.update_job is not None:
            job, callback = self.update_job
            if job.done():
                self.update_job = None
                callback(job)
        elif now >= self.next_update_check:
            self.check_updates(manual=False)

    def select_page(self, page):
        self.page = page
        self.page_choice.set(page.value)

    def cycle_page(self):
        pages = tuple(Page)
        self.select_page(pages[(pages.index(self.page) + 1) % len(pages)])

    def open_settings(self):
        if self.settings_dialog and self.settings_dialog.window.winfo_exists():
            self.settings_dialog.window.lift()
        else:
            self.settings_dialog = DisplaySettingsWindow(self.root, self.preferences, self.online, self.save_display)

    def save_display(self, hotkey, location):
        old_hotkey = self.tray.hotkey
        preferences = DisplayPreferences(self.tray.set_hotkey(hotkey), location)
        try:
            preferences.save(self.display_settings_path)
        except OSError:
            self.tray.set_hotkey(old_hotkey, validate_chord=False)
            raise
        self.preferences = preferences
        self.shortcut_hint.configure(text=preferences.hotkey)

    def update_online(self, now):
        for page, (key, job) in tuple(self.content_jobs.items()):
            if not job.done():
                continue
            del self.content_jobs[page]
            try:
                self.content_cache[key] = (job.result(), now)
            except Exception as error:
                self.next_fetch[key] = now + FETCH_RETRY
                self.content_errors[key] = str(error).strip() or type(error).__name__
            else:
                self.next_fetch[key] = now + FETCH_INTERVALS[page]
                self.content_errors.pop(key, None)

        if self.page is Page.PC or self.page in self.content_jobs:
            return
        location = self.preferences.location if self.page is Page.WEATHER else None
        key = (self.page, location)
        if now < self.next_fetch.get(key, 0) or (self.page is Page.WEATHER and location is None):
            return
        job = self.online(read_weather, location) if location is not None else self.online(read_headline)
        self.content_jobs[self.page] = (key, job)

    def selected_content(self, now):
        if self.page is Page.PC:
            return self.page, None, None, ""
        location = self.preferences.location if self.page is Page.WEATHER else None
        key = (self.page, location)
        data, fetched_at = self.content_cache.get(key, (None, 0))
        if now - fetched_at > MAX_CONTENT_AGE:
            data = None
        if data is not None:
            notice = "Poslední načtené údaje" if key in self.content_errors else ""
        elif self.page is Page.WEATHER and location is None:
            notice = "Nastav lokalitu"
        elif key in self.content_errors:
            notice = "Nedostupné"
        else:
            notice = "Načítám…"
        return self.page, location, data, notice

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
        self.sent_content = None
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
        self.sent_content = None
        self.refreshed(snapshot)
        self.connection_message("Panel je zapnutý." if on else "Panel je vypnutý.")

    def refreshed(self, snapshot):
        self.snapshot = snapshot
        self.next_refresh = monotonic() + REFRESH_INTERVAL

    def content_sent(self, content, snapshot):
        self.sent_content = content
        self.refreshed(snapshot)

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
        if self.update_button is not None:
            self.tick_update(now)
            if self.closing:
                return
        self.update_online(now)
        content = self.selected_content(now)
        if self.pending is None:
            changed = content != self.sent_content or (self.page is Page.PC and now >= self.next_refresh)
            if self.connected and self.powered and changed:
                self.submit(self.connection.refresh(*content), lambda snapshot: self.content_sent(content, snapshot))
            elif self.connected and now >= self.next_refresh:
                self.submit(self.connection.verify_connection(), self.refreshed)
            elif not self.connected and self.target_panel is not None and now >= self.retry_at:
                self.connect()
        if self.root.state() != "withdrawn":
            self.update_preview(now, content)
        self.root.after(80, self.tick)

    def update_preview(self, now, content):
        page, location, data, notice = content
        colon = int(now * 1000 / COLON_PHASE_MS) % 2 == 0
        offset = int(now * 22) if page is Page.NEWS and data is not None else 0
        key = (content, self.snapshot, colon if page is Page.PC and self.snapshot else None, offset, self.powered)
        if key == self.preview_key:
            return
        self.preview_key = key
        frame = None
        if page is Page.PC:
            detail = f"Obnova každých {REFRESH_INTERVAL} s"
            if self.snapshot:
                frame = render_status(*self.snapshot, show_colon=colon)
        elif page is Page.WEATHER:
            frame = render_weather(location, data, notice)
            detail = f"{location.label} · Open-Meteo" if location else "Vyber lokalitu v Nastavení."
        else:
            frame = render_news(data, notice, offset)
            detail = f"Novinky.cz · {data.title}" if data else "Zdroj: Novinky.cz, RSS Zpravodajství"
        if data is not None and notice:
            detail += f" · {notice}"
        error = self.content_errors.get((page, location))
        if error and data is None:
            detail += f" · {error[:160]}"
        if self.preview_detail.cget("text") != detail:
            self.preview_detail.configure(text=detail)
        if frame is not None and self.powered is not False:
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
        for _, job in self.content_jobs.values():
            job.cancel()
        if self.update_job is not None:
            self.update_job[0].cancel()
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
