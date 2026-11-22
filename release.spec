from pathlib import Path

root = Path(SPECPATH)
analysis = Analysis(
    [str(root / "led_gui.py")],
    datas=[(str(root / name), ".") for name in ("THIRD-PARTY-NOTICES.txt", "led-panel.ico")],
    excludes=["numpy"],
)

# Windows 10/11 supplies the Universal CRT. The VC++ runtime is installed separately.
system_runtime = ("api-ms-win-", "ext-ms-win-", "ucrtbase.dll", "vcruntime", "msvcp140", "concrt140", "vcomp140")
binaries = [entry for entry in analysis.binaries if not Path(entry[0]).name.lower().startswith(system_runtime)]

archive = PYZ(analysis.pure)
exe = EXE(archive, analysis.scripts, binaries, analysis.datas, name="LED-Panel",
          icon=str(root / "led-panel.ico"), console=False, upx=False)
