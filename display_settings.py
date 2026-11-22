import tkinter as tk
import webbrowser
from tkinter import ttk

from display_pages import NEWS_SOURCE, WEATHER_SOURCE, find_locations
from display_transitions import SPEED_LABELS, TRANSITION_LABELS, Transition


class DisplaySettingsWindow:
    def __init__(self, root, preferences, online, save, startup=None):
        self.online = online
        self.save = save
        self.location = preferences.location
        self.matches = [self.location] if self.location else []
        self.search = None
        self.window = tk.Toplevel(root)
        self.window.title("Nastavení displeje")
        self.window.transient(root)
        self.window.resizable(False, False)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        main = ttk.Frame(self.window, padding=20)
        main.pack(fill="both", expand=True)

        ttk.Label(main, text="Globální zkratka", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.hotkey = ttk.Entry(main, width=45)
        self.hotkey.insert(0, preferences.hotkey)
        self.hotkey.pack(fill="x", pady=(5, 2))
        ttk.Label(main, text="Např. Ctrl+Alt+F9 nebo §+). Prázdné pole zkratku vypne.").pack(anchor="w")

        ttk.Label(main, text="Přechod mezi obrazovkami", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(16, 5))
        transition_row = ttk.Frame(main)
        transition_row.pack(fill="x")
        effect_field = ttk.Frame(transition_row)
        effect_field.pack(side="left", fill="x", expand=True)
        ttk.Label(effect_field, text="Efekt").pack(anchor="w")
        self.transition = ttk.Combobox(effect_field, state="readonly", values=tuple(TRANSITION_LABELS.values()), width=21)
        self.transition.set(TRANSITION_LABELS[preferences.transition])
        self.transition.pack(fill="x", pady=(3, 0))
        self.transition.bind("<<ComboboxSelected>>", lambda _: self.update_speed_state())
        speed_field = ttk.Frame(transition_row)
        speed_field.pack(side="left", padx=(8, 0))
        ttk.Label(speed_field, text="Rychlost").pack(anchor="w")
        self.speed = ttk.Combobox(speed_field, state="readonly", values=tuple(SPEED_LABELS.values()), width=20)
        self.speed.set(SPEED_LABELS[preferences.speed])
        self.speed.pack(pady=(3, 0))
        self.update_speed_state()

        ttk.Label(main, text="Lokalita počasí", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(16, 5))
        search_row = ttk.Frame(main)
        search_row.pack(fill="x")
        self.query = ttk.Entry(search_row, width=41)
        self.query.pack(side="left", fill="x", expand=True)
        self.query.bind("<Return>", lambda _: self.find())
        self.search_button = ttk.Button(search_row, text="Vyhledat", command=self.find)
        self.search_button.pack(side="left", padx=(8, 0))
        self.results = ttk.Combobox(main, state="readonly", values=[item.label for item in self.matches])
        self.results.pack(fill="x", pady=(8, 0))
        if self.matches:
            self.results.current(0)
        else:
            self.results.set("Vyber výsledek hledání")
        self.status = ttk.Label(main, text="", wraplength=395, justify="left")
        self.status.pack(fill="x", pady=(9, 5))

        sources = ttk.Frame(main)
        sources.pack(fill="x")
        ttk.Label(sources, text="Zdroje pro osobní použití").pack(side="left")
        ttk.Button(sources, text="Open-Meteo", command=lambda: webbrowser.open(WEATHER_SOURCE)).pack(side="left", padx=(8, 4))
        ttk.Button(sources, text="Novinky.cz", command=lambda: webbrowser.open(NEWS_SOURCE)).pack(side="left")

        ttk.Label(main, text="Spuštění aplikace", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(16, 5))
        self.start_with_windows = None
        if startup is not None:
            enabled, hidden = startup
            self.start_with_windows = tk.BooleanVar(self.window, enabled)
            self.start_hidden = tk.BooleanVar(self.window, hidden)
            ttk.Checkbutton(main, text="Spustit s Windows", variable=self.start_with_windows,
                            command=self.update_startup_state).pack(anchor="w")
            self.hidden_box = ttk.Checkbutton(main, text="Spustit skrytě u hodin", variable=self.start_hidden)
            self.hidden_box.pack(anchor="w", padx=(18, 0))
            self.update_startup_state()
        self.remember_page = tk.BooleanVar(self.window, preferences.last_page is not None)
        ttk.Checkbutton(main, text="Obnovit poslední obrazovku", variable=self.remember_page).pack(anchor="w")

        self.save_button = ttk.Button(main, text="Uložit", command=self.apply)
        self.save_button.pack(anchor="e", pady=(14, 0))
        self.query.focus_set()

    def find(self):
        if self.search is not None:
            return
        query = self.query.get().strip()
        if len(query) < 2:
            self.status.configure(text="Zadej alespoň dva znaky názvu města.")
            return
        self.status.configure(text="Vyhledávám lokality…")
        self.search_button.state(["disabled"])
        self.save_button.state(["disabled"])
        self.search = self.online(find_locations, query)
        self.window.after(80, self.finish_search)

    def finish_search(self):
        if not self.search.done():
            self.window.after(80, self.finish_search)
            return
        try:
            matches = self.search.result()
        except Exception as error:
            self.status.configure(text=f"Vyhledávání se nezdařilo. {str(error)[:160]}")
        else:
            if matches:
                self.matches = matches
                self.results.configure(values=[item.label for item in matches])
                self.results.current(0)
                self.status.configure(text="Vyber správnou lokalitu a klikni na Uložit.")
            else:
                self.status.configure(text="Žádná lokalita se nenašla. Zkus upřesnit název města.")
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
            self.status.configure(text=str(error))
        except OSError:
            self.status.configure(text="Nastavení se nepodařilo uložit. Zkontroluj přístup k nastavení Windows a ke složce aplikace.")
        else:
            self.close()

    def update_speed_state(self):
        disabled = self.transition.get() == TRANSITION_LABELS[Transition.NONE]
        self.speed.configure(state="disabled" if disabled else "readonly")

    def update_startup_state(self):
        self.hidden_box.state(["!disabled"] if self.start_with_windows.get() else ["disabled"])

    def close(self):
        if self.search is not None:
            self.search.cancel()
        self.window.destroy()
