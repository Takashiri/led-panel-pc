import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from display_pages import Location, Page
from display_transitions import Transition, TransitionSpeed
from pc_status import ADDRESS_PATTERN


def settings_file():
    local = os.environ.get("LOCALAPPDATA")
    directory = Path(local) if local else Path.home() / "AppData" / "Local"
    return directory / "LED Panel PC" / "settings.json"


def read_settings(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_settings(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temporary:
        pending = Path(temporary.name)
        try:
            json.dump(data, temporary, ensure_ascii=False)
            temporary.close()
            pending.replace(path)
        finally:
            temporary.close()
            pending.unlink(missing_ok=True)


@dataclass(frozen=True)
class SavedPanel:
    name: str
    address: str
    powered: bool | None = None

    @classmethod
    def load(cls, path):
        data = read_settings(path)
        name, address, powered = (data.get(key) for key in ("name", "address", "powered"))
        if not isinstance(name, str) or not name.strip():
            return None
        if not isinstance(address, str) or not re.fullmatch(ADDRESS_PATTERN, address):
            return None
        if powered is not None and not isinstance(powered, bool):
            return None
        return cls(name, address.upper(), powered)

    def save(self, path):
        write_settings(path, asdict(self))


DEFAULT_HOTKEY = "Ctrl+Alt+F9"


def load_choice(data, key, default):
    try:
        return type(default)(data.get(key, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class DisplayPreferences:
    hotkey: str = DEFAULT_HOTKEY
    location: Location | None = None
    transition: Transition = Transition.SLIDE_LEFT
    speed: TransitionSpeed = TransitionSpeed.BALANCED
    last_page: Page | None = None

    @classmethod
    def load(cls, path):
        data = read_settings(path)
        hotkey = data.get("hotkey", DEFAULT_HOTKEY)
        last_page = data.get("last_page")
        return cls(
            hotkey if isinstance(hotkey, str) else DEFAULT_HOTKEY,
            Location.from_mapping(data.get("location")),
            load_choice(data, "transition", Transition.SLIDE_LEFT),
            load_choice(data, "speed", TransitionSpeed.BALANCED),
            Page.__members__.get(last_page) if isinstance(last_page, str) else None,
        )

    def save(self, path):
        data = asdict(self)
        data["last_page"] = self.last_page.name if self.last_page else None
        write_settings(path, data)
