"""Install stable Windows releases from this app's public GitHub repository."""

import ctypes
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from windows_http import get


APP_VERSION = "1.2.3"
REPOSITORY = "Takashiri/led-panel-pc"
LATEST_RELEASE = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
ASSET_NAME = "LED-Panel.exe"
USER_AGENT = f"LED-Panel-PC/{APP_VERSION}"
MAX_ASSET_SIZE = 64 * 1024 * 1024


@dataclass(frozen=True)
class ReleaseUpdate:
    version: str
    url: str
    sha256: str
    size: int


def version_parts(version):
    match = re.fullmatch(r"(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})", version)
    return tuple(map(int, match.groups())) if match else ()


def check_for_update(current_version=APP_VERSION):
    release = json.loads(get(LATEST_RELEASE, USER_AGENT))
    if not isinstance(release, dict):
        raise ValueError("GitHub vrátil neplatné údaje o vydání.")
    tag = release.get("tag_name")
    if (release.get("draft") is not False or release.get("prerelease") is not False
            or not isinstance(tag, str) or not tag.startswith("v")
            or version_parts(tag[1:]) <= version_parts(current_version)):
        return None

    url = f"https://github.com/{REPOSITORY}/releases/download/{tag}/{ASSET_NAME}"
    assets = release.get("assets")
    if not isinstance(assets, list):
        assets = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        if (asset.get("name") == ASSET_NAME and asset.get("state") == "uploaded"
                and asset.get("browser_download_url") == url):
            digest = asset.get("digest")
            size = asset.get("size")
            if (isinstance(digest, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
                    and type(size) is int and 0 < size <= MAX_ASSET_SIZE):
                return ReleaseUpdate(tag[1:], url, digest.removeprefix("sha256:"), size)
    raise ValueError(f"Vydání {tag} nemá ověřitelný soubor {ASSET_NAME}.")


def download_update(update):
    data = get(update.url, USER_AGENT, max_body=update.size)
    if len(data) != update.size or hashlib.sha256(data).hexdigest() != update.sha256:
        raise ValueError("Stažený soubor neodpovídá kontrolnímu součtu na GitHubu.")
    return data


# Windows holds the running EXE open. This script runs in a separate process
# and receives paths through the environment so they are never interpreted as code.
INSTALL_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$target = $env:LED_PANEL_UPDATE_TARGET
$pending = $env:LED_PANEL_UPDATE_PENDING
$backup = $target + '.previous'
try {
    $parent = Get-Process -Id ([int]$env:LED_PANEL_UPDATE_PID) -ErrorAction SilentlyContinue
    if ($parent -and -not $parent.WaitForExit(30000)) {
        throw 'The running app did not exit in time.'
    }
    # Wait for the PyInstaller launcher, which exits after the GUI process.
    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    while ($true) {
        try {
            [IO.File]::Replace($pending, $target, $backup)
            break
        } catch [IO.IOException], [UnauthorizedAccessException] {
            if ([DateTime]::UtcNow -ge $deadline -or -not [IO.File]::Exists($target) -or
                -not [IO.File]::Exists($pending)) { throw }
            Start-Sleep -Milliseconds 250
        }
    }
    try {
        $start = New-Object Diagnostics.ProcessStartInfo
        $start.FileName = $target
        $start.WorkingDirectory = [IO.Path]::GetDirectoryName($target)
        $start.UseShellExecute = $false
        $start.CreateNoWindow = $true
        [void][Diagnostics.Process]::Start($start)
    } catch {
        [IO.File]::Replace($backup, $target, $null)
        throw
    }
} catch {
    if (-not [IO.File]::Exists($target) -and [IO.File]::Exists($backup)) {
        [IO.File]::Move($backup, $target)
    }
    Add-Type -AssemblyName System.Windows.Forms
    [void][Windows.Forms.MessageBox]::Show($_.Exception.Message, 'LED Panel PC - aktualizace selhala')
    exit 1
} finally {
    [IO.File]::Delete($pending)
}
"""


def install_update(data):
    if not getattr(sys, "frozen", False):
        raise RuntimeError("Aktualizace je dostupná v samostatném souboru EXE.")
    target = Path(sys.executable)
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    with NamedTemporaryFile(dir=target.parent, prefix=".led-panel-update-", suffix=".tmp", delete=False) as file:
        pending = Path(file.name)
        try:
            file.write(data)
            file.close()
            env = os.environ | {
                "LED_PANEL_UPDATE_TARGET": str(target),
                "LED_PANEL_UPDATE_PENDING": str(pending),
                "LED_PANEL_UPDATE_PID": str(os.getpid()),
                "PYINSTALLER_RESET_ENVIRONMENT": "1",
            }
            ctypes.windll.kernel32.SetDllDirectoryW(None)
            try:
                subprocess.Popen([str(powershell), "-NoProfile", "-NonInteractive", "-Command", INSTALL_SCRIPT],
                                 env=env, cwd=powershell.parent, creationflags=subprocess.CREATE_NO_WINDOW)
            finally:
                ctypes.windll.kernel32.SetDllDirectoryW(str(sys._MEIPASS))
        except OSError:
            file.close()
            pending.unlink(missing_ok=True)
            raise
