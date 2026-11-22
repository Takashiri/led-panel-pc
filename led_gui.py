import asyncio
import sys
import tkinter as tk
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from threading import Thread
from time import monotonic
from tkinter import messagebox, ttk

import psutil
from PIL import Image, ImageTk
from pypixelcolor import AsyncClient

import windows_startup
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
from display_settings import DisplaySettings
from display_transitions import Transition, TransitionSpeed, make_transition
from gui_style import ACCENT, BACKGROUND, BORDER, ERROR, FIELD, FONT, MUTED, configure_theme, dark_caption, make_card
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
from windows_tray import TrayIcon, show_foreground_window

ICON_PATH = Path(__file__).with_name("led-panel.ico")
RECONNECT_DELAY = 10
FETCH_INTERVALS = {Page.WEATHER: 900, Page.NEWS: 300}
FETCH_RETRY = 60
MAX_CONTENT_AGE = 3600
UPDATE_CHECK_INTERVAL = 24 * 60 * 60


def render_page_frame(content, snapshot, *, show_colon=True, news_offset=0):
    page, location, data, notice = content
    if page is Page.PC:
        return render_status(*snapshot, show_colon=show_colon) if snapshot else None
    if page is Page.WEATHER:
        return render_weather(location, data, notice)
    return render_news(data, notice, news_offset)


class PanelConnection:
    def __init__(self):
        self.panel = None
        self.displayed = None

    async def connect(self, address):
        panel = AsyncClient(address)
        await panel.connect()
        self.panel = panel
        info = panel.get_device_info()
        if (info.width, info.height) != PANEL_SIZE:
            await self.disconnect()
            raise RuntimeError(f"Panel má {info.width} × {info.height} px. Aplikace podporuje 64 × 16 px.")

    async def disconnect(self):
        self.displayed = None
        if self.panel is not None:
            panel, self.panel = self.panel, None
            await panel.disconnect()

    async def set_power(self, on):
        if on:
            await self.panel.set_brightness(PANEL_BRIGHTNESS)
        await self.panel.set_power(on)
        self.displayed = None
        if on:
            psutil.cpu_percent()
            await asyncio.sleep(0.5)

    async def refresh(self, page, location, data, notice, *, effect=Transition.NONE, speed=TransitionSpeed.BALANCED):
        status = read_status() if page is Page.PC else None
        frame = render_page_frame((page, location, data, notice), status)
        if self.displayed is not None and self.displayed[0] is not page and effect is not Transition.NONE:
            animation = make_transition(self.displayed[1], frame, effect, speed)
            await self.panel.send_image_hex(animation.panel_gif(), ".gif", save_slot=0)
            await asyncio.sleep(animation.duration)

        if page is Page.PC:
            await self.panel.send_image_hex(encode_status_animation(*status), ".gif", save_slot=0)
        elif page is Page.NEWS and data is not None:
            await self.panel.send_text(data.ticker, animation="scroll_left", speed=NEWS_SPEED,
                                       color=NEWS_COLOR, font=ticker_font(), save_slot=0)
        else:
            await self.panel.send_image_hex(png_hex(frame), ".png", save_slot=0)
        self.displayed = page, frame
        return status

    async def verify_connection(self):
        self.panel.get_device_info()


class PanelWindow:
    def __init__(self, root):
        self.root = root
        self.settings_path = settings_file()
        self.display_settings_path = self.settings_path.with_name("display.json")
        self.preferences = DisplayPreferences.load(self.display_settings_path)
        self.settings = None
        self.page = self.preferences.last_page or Page.PC
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
        self.preview_page = None
        self.preview_frame = None
        self.preview_animation = None
        self.preview_size = PANEL_SIZE
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
        root.geometry("752x625")
        root.minsize(560, 535)
        root.protocol("WM_DELETE_WINDOW", self.hide_window)
        configure_theme(root)
        root.after_idle(dark_caption, root)
        main = ttk.Frame(root, padding=(24, 19, 24, 16))
        main.pack(fill="both", expand=True)
        ttk.Label(main, text="LED Panel pro PC", style="Title.TLabel").pack(anchor="w", pady=(0, 13))
        self.tabs = ttk.Notebook(main)
        self.tabs.pack(fill="both", expand=True)
        self.control_page = ttk.Frame(self.tabs, padding=(0, 12, 0, 0))
        self.settings_page = ttk.Frame(self.tabs, padding=(0, 12, 0, 0))
        self.tabs.add(self.control_page, text="Ovládání")
        self.tabs.add(self.settings_page, text="Nastavení")
        self.tabs.enable_traversal()
        self.tabs.bind("<<NotebookTabChanged>>", self.tab_changed)
        self.build_controls(self.control_page)

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

    def build_controls(self, page):
        preview_card, preview_body = make_card(page)
        preview_card.pack(fill="both", expand=True)
        toolbar = ttk.Frame(preview_body, style="Card.TFrame")
        toolbar.pack(fill="x", pady=(0, 11))
        ttk.Label(toolbar, text="Náhled displeje", style="Heading.Card.TLabel").pack(side="left")
        screens = ttk.Frame(toolbar, style="Card.TFrame")
        screens.pack(side="right")
        self.page_choice = tk.StringVar(self.root, self.page.value)
        for display_page in Page:
            ttk.Radiobutton(screens, text=display_page.value, value=display_page.value, variable=self.page_choice,
                            style="Screen.Toolbutton", command=lambda choice=display_page: self.select_page(choice)
                            ).pack(side="left", padx=(4, 0))
        self.preview = tk.Canvas(preview_body, width=1, height=1, background=FIELD, highlightbackground=BORDER,
                                 highlightthickness=1, borderwidth=0)
        self.preview.pack(fill="both", expand=True)
        self.preview_image = self.preview.create_image(0, 0)
        self.preview_text = self.preview.create_text(0, 0, fill=MUTED, font=FONT, justify="center")
        self.preview.bind("<Configure>", self.resize_preview)

        preview_footer = ttk.Frame(preview_body, style="Card.TFrame")
        preview_footer.pack(fill="x", pady=(9, 0))
        self.shortcut_hint = ttk.Label(preview_footer, style="Muted.Card.TLabel")
        self.shortcut_hint.pack(side="right", anchor="n", padx=(12, 0))
        self.preview_detail = ttk.Label(preview_footer, style="Muted.Card.TLabel", justify="left")
        self.preview_detail.pack(side="left", fill="x", expand=True)

        connection_card, connection_body = make_card(page)
        connection_card.pack(fill="x", pady=(12, 0))
        power_row = ttk.Frame(connection_body, style="Card.TFrame")
        power_row.pack(fill="x")
        ttk.Label(power_row, text="Připojení Bluetooth", style="Heading.Card.TLabel").pack(side="left")
        self.off_button = ttk.Button(power_row, text="Vypnout", command=lambda: self.set_power(False))
        self.off_button.pack(side="right")
        self.on_button = ttk.Button(power_row, text="Zapnout", style="Primary.TButton", command=lambda: self.set_power(True))
        self.on_button.pack(side="right", padx=(8, 7))
        ttk.Label(power_row, text="Napájení panelu", style="Muted.Card.TLabel").pack(side="right")

        device_row = ttk.Frame(connection_body, style="Card.TFrame")
        device_row.pack(fill="x", pady=(9, 7))
        self.device = ttk.Combobox(device_row, state="disabled", font=FONT, width=1)
        self.device.pack(side="left", fill="x", expand=True)
        self.scan_button = ttk.Button(device_row, text="Vyhledat", command=self.scan)
        self.scan_button.pack(side="left", padx=(8, 0))
        self.connect_button = ttk.Button(device_row, text="Připojit", command=self.toggle_connection)
        self.connect_button.pack(side="left", padx=(8, 0))
        self.message = ttk.Label(connection_body, text="Připraveno k vyhledání panelu.", style="Muted.Card.TLabel", justify="left")
        self.message.pack(fill="x")

        self.update_button = None
        if getattr(sys, "frozen", False):
            update_row = ttk.Frame(page)
            update_row.pack(fill="x", pady=(12, 0))
            self.update_button = ttk.Button(update_row, text="Zkontrolovat aktualizace", command=self.update_action)
            self.update_button.pack(side="right")
            self.update_status = ttk.Label(update_row, text=f"Verze {APP_VERSION}", style="Muted.TLabel", justify="left")
            self.update_status.pack(side="left", fill="x", expand=True, padx=(0, 12))
            update_row.bind("<Configure>", lambda event: self.update_status.configure(
                wraplength=max(1, event.width - self.update_button.winfo_reqwidth() - 12)))

        connection_body.bind("<Configure>", lambda event: self.message.configure(wraplength=max(1, event.width - 32)))
        preview_footer.bind("<Configure>", self.resize_preview_footer)

    def resize_preview_footer(self, event):
        available = event.width - self.shortcut_hint.winfo_reqwidth() - 12
        self.preview_detail.configure(wraplength=max(1, available))

    def resize_preview(self, event):
        scale = max(1, min((event.width - 24) // PANEL_SIZE[0], (event.height - 24) // PANEL_SIZE[1]))
        size = (PANEL_SIZE[0] * scale, PANEL_SIZE[1] * scale)
        center = (event.width // 2, event.height // 2)
        self.preview.coords(self.preview_image, *center)
        self.preview.coords(self.preview_text, *center)
        self.preview.itemconfigure(self.preview_text, width=max(1, event.width - 28))
        if size != self.preview_size:
            self.preview_size = size
            if self.preview_frame is not None:
                self.draw_preview_image(self.preview_frame)

    def draw_preview_image(self, frame):
        self.photo = ImageTk.PhotoImage(frame.resize(self.preview_size, Image.Resampling.NEAREST))
        self.preview.itemconfigure(self.preview_image, image=self.photo)
        self.preview.itemconfigure(self.preview_text, text="")

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
            ("Otevřít", self.show_window),
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
        if page is Page.PC and self.snapshot is None and self.powered is True:
            self.snapshot = read_status()
        self.page_choice.set(page.value)
        if self.preferences.last_page is not None and self.preferences.last_page is not page:
            preferences = replace(self.preferences, last_page=page)
            try:
                preferences.save(self.display_settings_path)
            except OSError:
                self.message.configure(text="Poslední obrazovku se nepodařilo uložit.", foreground=ERROR)
            else:
                self.preferences = preferences

    def cycle_page(self):
        pages = tuple(Page)
        self.select_page(pages[(pages.index(self.page) + 1) % len(pages)])

    def tab_changed(self, _event):
        if self.tabs.select() != str(self.settings_page):
            return
        self.preview_animation = self.preview_page = self.preview_key = None
        if self.settings is not None:
            return
        startup = None
        if getattr(sys, "frozen", False):
            try:
                command = windows_startup.read_command()
            except OSError as error:
                messagebox.showerror("Spuštění s Windows", str(error), parent=self.root)
            else:
                startup = command is not None, bool(command and command.endswith(f" {windows_startup.TRAY_ARGUMENT}"))
        self.settings = DisplaySettings(self.settings_page, self.preferences, self.online, self.save_display, startup)
        self.settings.pack(fill="both", expand=True)

    def save_display(self, hotkey, location, effect, speed, *, remember_page, startup):
        old_hotkey = self.tray.hotkey
        with ExitStack() as rollback:
            hotkey = self.tray.set_hotkey(hotkey)
            if hotkey != old_hotkey:
                rollback.callback(self.tray.set_hotkey, old_hotkey, validate_chord=False)
            if startup is not None:
                enabled, hidden = startup
                previous = windows_startup.read_command()
                command = windows_startup.make_command(sys.executable, hidden) if enabled else None
                if command != previous:
                    windows_startup.write_command(command)
                    rollback.callback(windows_startup.write_command, previous)
            preferences = DisplayPreferences(hotkey, location, effect, speed, self.page if remember_page else None)
            preferences.save(self.display_settings_path)
            rollback.pop_all()
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
        self.message.configure(text="Vyhledávám LED panely v okolí…", foreground=MUTED)
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
        self.message.configure(text=text, foreground=MUTED)

    def toggle_connection(self):
        if self.pending is not None:
            return
        if self.connected:
            self.target_panel = None
            self.message.configure(text="Odpojuji panel…", foreground=MUTED)
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
        self.message.configure(text=f"Připojuji {panel.name}…", foreground=MUTED)
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
        self.message.configure(text=text, foreground=ACCENT)

    def disconnected(self, _):
        self.connected = False
        self.powered = self.snapshot = None
        self.sent_content = None
        self.message.configure(text="Panel je odpojený.", foreground=MUTED)

    def set_power(self, on):
        if not self.can_set_power(on):
            return
        self.target_panel = replace(self.target_panel, powered=on)
        self.remember_panel()
        self.message.configure(text="Zapínám panel…" if on else "Vypínám panel…", foreground=MUTED)
        self.submit(self.connection.set_power(on), lambda snapshot: self.power_changed(on, snapshot))

    def power_changed(self, on, snapshot):
        self.powered = on
        self.sent_content = None
        self.snapshot = snapshot
        self.refreshed(snapshot)
        self.connection_message("Panel je zapnutý." if on else "Panel je vypnutý.")

    def refreshed(self, snapshot):
        if snapshot is not None:
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
                self.message.configure(text=f"Bluetooth: {error}.{retry}", foreground=ERROR)
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
                update = self.connection.refresh(*content, effect=self.preferences.transition, speed=self.preferences.speed)
                self.submit(update, lambda snapshot: self.content_sent(content, snapshot))
            elif self.connected and now >= self.next_refresh:
                self.submit(self.connection.verify_connection(), self.refreshed)
            elif not self.connected and self.target_panel is not None and now >= self.retry_at:
                self.connect()
        if self.root.state() in ("normal", "zoomed") and self.tabs.select() == str(self.control_page):
            self.update_preview(now, content)
        self.root.after(20 if self.preview_animation else 80, self.tick)

    def update_preview(self, now, content):
        page, location, data, notice = content
        colon = int(now * 1000 / COLON_PHASE_MS) % 2 == 0
        offset = int(now * 22) if page is Page.NEWS and data is not None else 0
        key = (content, self.snapshot, colon if page is Page.PC and self.snapshot else None, offset, self.powered)
        if key == self.preview_key and self.preview_animation is None:
            return
        self.preview_key = key
        if page is Page.PC:
            detail = f"Obnova každých {REFRESH_INTERVAL} s"
        elif page is Page.WEATHER:
            detail = f"{location.label} · Open-Meteo" if location else "Vyber lokalitu v Nastavení."
        else:
            detail = f"Novinky.cz · {data.title}" if data else "Zdroj: Novinky.cz, RSS Zpravodajství"
        if data is not None and notice:
            detail += f" · {notice}"
        error = self.content_errors.get((page, location))
        if error and data is None:
            detail += f" · {error[:160]}"
        if self.preview_detail.cget("text") != detail:
            self.preview_detail.configure(text=detail)
        frame = render_page_frame(content, self.snapshot, show_colon=colon, news_offset=offset)
        frame = self.transition_preview(page, frame, now)
        if frame is not None:
            if frame is not self.preview_frame:
                self.draw_preview_image(frame)
        else:
            self.preview.itemconfigure(self.preview_image, image="")
            self.photo = None
            text = "Displej je vypnutý" if self.powered is False else "Živý náhled se zobrazí po zapnutí"
            self.preview.itemconfigure(self.preview_text, text=text)
        self.preview_frame = frame

    def transition_preview(self, page, frame, now):
        previous_page = self.preview_page
        self.preview_page = page
        if self.powered is False:
            self.preview_animation = None
            return None
        if previous_page is not page:
            self.preview_animation = None
            effect = self.preferences.transition
            if previous_page is not None and effect is not Transition.NONE and (self.preview_frame or frame):
                blank = Image.new("RGB", PANEL_SIZE)
                animation = make_transition(self.preview_frame or blank, frame or blank, effect, self.preferences.speed)
                self.preview_animation = now, animation
        if self.preview_animation is not None:
            started_at, animation = self.preview_animation
            index = int((now - started_at) * 1000 / animation.frame_ms)
            if index < len(animation.frames):
                return animation.frames[index]
            self.preview_animation = None
        return frame

    def show_window(self):
        show_foreground_window(self.root)

    def hide_window(self):
        if self.tray.available:
            self.preview_animation = self.preview_page = self.preview_key = None
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
        if self.settings is not None:
            self.settings.cancel_search()
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


def main():
    hidden = windows_startup.TRAY_ARGUMENT in sys.argv[1:]
    if TrayIcon.open_existing(show=not hidden):
        return
    window = tk.Tk()
    if hidden:
        window.withdraw()
    app = PanelWindow(window)
    if hidden and not app.tray.available:
        window.deiconify()
    window.mainloop()


if __name__ == "__main__":
    main()
