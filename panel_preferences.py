import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from pc_status import ADDRESS_PATTERN


def settings_file():
    local = os.environ.get("LOCALAPPDATA")
    directory = Path(local) if local else Path.home() / "AppData" / "Local"
    return directory / "LED Panel PC" / "settings.json"


@dataclass(frozen=True)
class SavedPanel:
    name: str
    address: str
    powered: bool | None = None

    @classmethod
    def load(cls, path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        name, address, powered = (data.get(key) for key in ("name", "address", "powered"))
        if not isinstance(name, str) or not name.strip():
            return None
        if not isinstance(address, str) or not re.fullmatch(ADDRESS_PATTERN, address):
            return None
        if powered is not None and not isinstance(powered, bool):
            return None
        return cls(name, address.upper(), powered)

    def save(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temporary:
            pending = Path(temporary.name)
            try:
                json.dump(asdict(self), temporary, ensure_ascii=False)
                temporary.close()
                pending.replace(path)
            finally:
                temporary.close()
                pending.unlink(missing_ok=True)
