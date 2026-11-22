import tkinter as tk
import webbrowser
from tkinter import ttk

from display_pages import NEWS_SOURCE, WEATHER_SOURCE, find_locations
from display_transitions import SPEED_LABELS, TRANSITION_LABELS, Transition
from gui_style import ACCENT, BACKGROUND, ERROR, MUTED, make_card


class DisplaySettings(ttk.Frame):
    def __init__(self, parent, preferences, online, save, startup=None):
        super().__init__(parent)
        self.online = online
        self.save = save
        self.location = preferences.location
        self.matches = [self.location] if self.location else []
        self.search = None

        footer = ttk.Frame(self, padding=(0, 10, 0, 0))
        footer.pack(side="bottom", fill="x")
        self.save_button = ttk.Button(footer, text="Uložit", style="Primary.TButton", command=self.apply)
        self.save_button.pack(side="right")
        self.status = ttk.Label(footer, style="Muted.TLabel", justify="left")
        self.status.pack(side="left", fill="x", expand=True, padx=(0, 12))
        footer.bind("<Configure>", lambda event: self.status.configure(
            wraplength=max(1, event.width - self.save_button.winfo_reqwidth() - 12)))

        self.body = ttk.Frame(self)
        self.body.pack(fill="both", expand=True)
        self.body.columnconfigure(0, weight=1)
        self.body.rowconfigure(0, weight=1)
        self.viewport = tk.Canvas(self.body, width=1, height=1, background=BACKGROUND, highlightthickness=0)
        self.viewport.grid(row=0, column=0, sticky="nsew")
        self.scrollbar = ttk.Scrollbar(self.body, orient="vertical", command=self.viewport.yview)
        self.scrollbar.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        self.scrollbar.grid_remove()
        self.viewport.configure(yscrollcommand=self.scrollbar.set)
        self.content = ttk.Frame(self.viewport)
        self.content_item = self.viewport.create_window(0, 0, window=self.content, anchor="nw")
        self.columns = 0
        self.cards = []
        self.viewport.bind("<Configure>", self.layout_cards)
        self.content.bind("<Configure>", self.update_scroll)
        self.winfo_toplevel().bind("<MouseWheel>", self.scroll_from_mouse, add="+")

        shortcut = self.add_card("Globální zkratka")
        self.hotkey = ttk.Entry(shortcut, width=1)
        self.hotkey.insert(0, preferences.hotkey)
        self.hotkey.pack(fill="x")
        shortcut_help = ttk.Label(shortcut, style="Muted.Card.TLabel", justify="left",
                                  text="Např. Ctrl+Alt+F9 nebo §+). Prázdné pole zkratku vypne.")
        shortcut_help.pack(fill="x", pady=(7, 0))
        shortcut.bind("<Configure>", lambda event: shortcut_help.configure(wraplength=max(1, event.width - 32)))

        transition = self.add_card("Přechod mezi obrazovkami")
        ttk.Label(transition, text="Efekt", style="Muted.Card.TLabel").pack(anchor="w")
        self.transition = ttk.Combobox(transition, state="readonly", values=tuple(TRANSITION_LABELS.values()), width=1)
        self.transition.set(TRANSITION_LABELS[preferences.transition])
        self.transition.pack(fill="x", pady=(3, 0))
        self.transition.bind("<<ComboboxSelected>>", lambda _: self.update_speed_state())
        ttk.Label(transition, text="Rychlost", style="Muted.Card.TLabel").pack(anchor="w", pady=(8, 0))
        self.speed = ttk.Combobox(transition, state="readonly", values=tuple(SPEED_LABELS.values()), width=1)
        self.speed.set(SPEED_LABELS[preferences.speed])
        self.speed.pack(fill="x", pady=(3, 0))
        self.update_speed_state()

        weather = self.add_card("Lokalita počasí")
        ttk.Label(weather, text="Město nebo obec", style="Muted.Card.TLabel").pack(anchor="w", pady=(0, 3))
        search_row = ttk.Frame(weather, style="Card.TFrame")
        search_row.pack(fill="x")
        self.query = ttk.Entry(search_row, width=1)
        self.query.pack(side="left", fill="x", expand=True)
        self.query.bind("<Return>", lambda _: self.find())
        self.search_button = ttk.Button(search_row, text="Vyhledat", command=self.find)
        self.search_button.pack(side="left", padx=(8, 0))
        self.results = ttk.Combobox(weather, state="readonly", values=[item.label for item in self.matches], width=1)
        self.results.pack(fill="x", pady=(8, 0))
        if self.matches:
            self.results.current(0)
        else:
            self.results.set("Vyber výsledek hledání")
        self.search_status = ttk.Label(weather, style="Muted.Card.TLabel", justify="left")
        self.search_status.pack(fill="x", pady=(5, 3))
        weather.bind("<Configure>", lambda event: self.search_status.configure(wraplength=max(1, event.width - 32)))
        sources = ttk.Frame(weather, style="Card.TFrame")
        sources.pack(fill="x", pady=(2, 0))
        ttk.Button(sources, text="Open-Meteo", command=lambda: webbrowser.open(WEATHER_SOURCE)).pack(side="left", padx=(0, 6))
        ttk.Button(sources, text="Novinky.cz", command=lambda: webbrowser.open(NEWS_SOURCE)).pack(side="left")

        launch = self.add_card("Spuštění aplikace")
        self.start_with_windows = None
        if startup is not None:
            enabled, hidden = startup
            self.start_with_windows = tk.BooleanVar(self, enabled)
            self.start_hidden = tk.BooleanVar(self, hidden)
            ttk.Checkbutton(launch, text="Spustit s Windows", variable=self.start_with_windows,
                            command=self.update_startup_state).pack(anchor="w")
            self.hidden_box = ttk.Checkbutton(launch, text="Spustit skrytě u hodin", variable=self.start_hidden)
            self.hidden_box.pack(anchor="w", padx=(18, 0))
            self.update_startup_state()
        self.remember_page = tk.BooleanVar(self, preferences.last_page is not None)
        ttk.Checkbutton(launch, text="Obnovit poslední obrazovku", variable=self.remember_page).pack(anchor="w")

    def add_card(self, title):
        border, card = make_card(self.content)
        self.cards.append(border)
        ttk.Label(card, text=title, style="Heading.Card.TLabel").pack(anchor="w", pady=(0, 9))
        return card

    def layout_cards(self, event):
        self.viewport.itemconfigure(self.content_item, width=event.width)
        columns = 2 if self.body.winfo_width() >= 650 else 1
        if columns != self.columns:
            self.columns = columns
            self.content.columnconfigure(0, weight=1, uniform="settings")
            self.content.columnconfigure(1, weight=1 if columns == 2 else 0, uniform="settings" if columns == 2 else "")
            for index, card in enumerate(self.cards):
                row, column = divmod(index, columns)
                gap = ((0, 6) if column == 0 else (6, 0)) if columns == 2 else 0
                card.grid(row=row, column=column, sticky="nsew", padx=gap, pady=(0, 12))
        self.update_scroll()

    def update_scroll(self, _event=None):
        self.viewport.configure(scrollregion=self.viewport.bbox(self.content_item))
        if self.content.winfo_reqheight() > self.viewport.winfo_height():
            self.scrollbar.grid()
        else:
            self.scrollbar.grid_remove()
            self.viewport.yview_moveto(0)

    def scroll_from_mouse(self, event):
        if not self.viewport.winfo_ismapped() or event.delta == 0:
            return
        x = event.x_root - self.viewport.winfo_rootx()
        y = event.y_root - self.viewport.winfo_rooty()
        if 0 <= x < self.viewport.winfo_width() and 0 <= y < self.viewport.winfo_height():
            if self.viewport.yview() != (0.0, 1.0):
                self.viewport.yview_scroll(-3 if event.delta > 0 else 3, "units")
                return "break"

    def find(self):
        if self.search is not None:
            return
        query = self.query.get().strip()
        if len(query) < 2:
            self.search_status.configure(text="Zadej alespoň dva znaky názvu města.", foreground=ERROR)
            return
        self.search_status.configure(text="Vyhledávám lokality…", foreground=MUTED)
        self.search_button.state(["disabled"])
        self.save_button.state(["disabled"])
        self.search = self.online(find_locations, query)
        self.after(80, self.finish_search)

    def finish_search(self):
        if self.search is None:
            return
        if not self.search.done():
            self.after(80, self.finish_search)
            return
        try:
            matches = self.search.result()
        except Exception as error:
            self.search_status.configure(text=f"Vyhledávání se nezdařilo. {str(error)[:160]}", foreground=ERROR)
        else:
            if matches:
                self.matches = matches
                self.results.configure(values=[item.label for item in matches])
                self.results.current(0)
                self.search_status.configure(text="Vyber lokalitu a klikni na Uložit.", foreground=MUTED)
            else:
                self.search_status.configure(text="Žádná lokalita se nenašla. Zkus upřesnit název města.", foreground=MUTED)
        self.search = None
        self.search_button.state(["!disabled"])
        self.save_button.state(["!disabled"])

    def apply(self):
        selected = self.results.current()
        location = self.matches[selected] if selected >= 0 else self.location
        effect = tuple(TRANSITION_LABELS)[self.transition.current()]
        speed = tuple(SPEED_LABELS)[self.speed.current()]
        startup = None if self.start_with_windows is None else (self.start_with_windows.get(), self.start_hidden.get())
        try:
            self.save(self.hotkey.get(), location, effect, speed, remember_page=self.remember_page.get(), startup=startup)
        except ValueError as error:
            self.status.configure(text=str(error), foreground=ERROR)
        except OSError:
            self.status.configure(text="Nastavení se nepodařilo uložit. Zkontroluj přístup k nastavení Windows a ke složce aplikace.",
                                  foreground=ERROR)
        else:
            self.location = location
            self.status.configure(text="Nastavení uloženo.", foreground=ACCENT)

    def update_speed_state(self):
        disabled = self.transition.get() == TRANSITION_LABELS[Transition.NONE]
        self.speed.configure(state="disabled" if disabled else "readonly")

    def update_startup_state(self):
        self.hidden_box.state(["!disabled"] if self.start_with_windows.get() else ["disabled"])

    def cancel_search(self):
        if self.search is not None:
            self.search.cancel()
            self.search = None
