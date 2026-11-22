import argparse
import asyncio
import io
import re
import sys
from datetime import datetime
from pathlib import Path

import psutil
from bleak import BleakScanner
from bleak.exc import BleakError
from PIL import Image, ImageDraw
from pypixelcolor import AsyncClient

PANEL_SIZE = (64, 16)
PANEL_SERVICE = "000000fa-0000-1000-8000-00805f9b34fb"
PANEL_BRIGHTNESS = 0
COLON_PHASE_MS = 500
REFRESH_INTERVAL = 10
DEVICE_PREFIXES = ("LED_BLE", "IPIXEL", "BRILONER")
ADDRESS_PATTERN = r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}"

# Three-pixel-wide glyphs stay sharp at the panel's native resolution.
GLYPHS = {
    "0": (7, 5, 5, 5, 7), "1": (2, 6, 2, 2, 7), "2": (7, 1, 7, 4, 7),
    "3": (7, 1, 7, 1, 7), "4": (5, 5, 7, 1, 1), "5": (7, 4, 7, 1, 7),
    "6": (7, 4, 7, 5, 7), "7": (7, 1, 2, 2, 2), "8": (7, 5, 7, 5, 7),
    "9": (7, 5, 7, 1, 7), "%": (5, 1, 2, 4, 5),
    "A": (2, 5, 7, 5, 5), "C": (7, 4, 4, 4, 7), "M": (5, 7, 7, 5, 5),
    "P": (6, 5, 6, 4, 4), "R": (6, 5, 6, 5, 5), "U": (5, 5, 5, 5, 7),
}


def draw_text(draw, text, x, y, color, scale=1):
    for char in text:
        for dy, row in enumerate(GLYPHS[char]):
            for dx in range(3):
                if row & (4 >> dx):
                    left, top = x + dx * scale, y + dy * scale
                    draw.rectangle((left, top, left + scale - 1, top + scale - 1), fill=color)
        x += 3 * scale + 1


def render_status(clock, cpu, ram, *, show_colon=True):
    image = Image.new("RGB", PANEL_SIZE)
    draw = ImageDraw.Draw(image)
    hours, minutes = clock.split(":")
    draw_text(draw, hours, 1, 3, "#e8f4ff", scale=2)
    draw_text(draw, minutes, 18, 3, "#e8f4ff", scale=2)
    if show_colon:
        draw.rectangle((15, 5, 16, 6), fill="#61c9ff")
        draw.rectangle((15, 9, 16, 10), fill="#61c9ff")
    draw.line((32, 1, 32, 14), fill="#35495e")

    for label, value, y, color in (("CPU", cpu, 1, "#61c9ff"), ("RAM", ram, 9, "#8fea83")):
        draw_text(draw, label, 35, y, color)
        percent = f"{value}%"
        draw_text(draw, percent, 64 - 4 * len(percent), y, "#e8f4ff")
        draw.line((35, y + 6, 62, y + 6), fill="#29394c")
        pixels = round(28 * value / 100)
        if pixels:
            draw.line((35, y + 6, 34 + pixels, y + 6), fill=color)
    return image


def encode_status_animation(clock, cpu, ram):
    visible = render_status(clock, cpu, ram)
    hidden = render_status(clock, cpu, ram, show_colon=False)
    with io.BytesIO() as buffer:
        visible.save(
            buffer,
            format="GIF",
            save_all=True,
            append_images=[hidden],
            duration=COLON_PHASE_MS,
            loop=0,
            disposal=2,
        )
        return buffer.getvalue().hex()


def read_status():
    return (
        datetime.now().strftime("%H:%M"),
        round(psutil.cpu_percent()),
        round(psutil.virtual_memory().percent),
    )


async def find_panels():
    advertisements = await BleakScanner.discover(timeout=8, return_adv=True)
    panels = []
    for device, advertisement in advertisements.values():
        name = advertisement.local_name or device.name or ""
        if name.upper().startswith(DEVICE_PREFIXES) or PANEL_SERVICE in advertisement.service_uuids:
            panels.append((name or "LED panel", device.address, advertisement.rssi))
    return sorted(panels, key=lambda panel: (-panel[2], panel[0], panel[1]))


async def show_status(address, interval, once):
    while True:
        try:
            print(f"Připojuji se k {address}…", flush=True)
            async with AsyncClient(address) as panel:
                info = panel.get_device_info()
                if (info.width, info.height) != PANEL_SIZE:
                    print(f"Panel hlásí {info.width} × {info.height} px. Tato verze podporuje 64 × 16 px.")
                    return 1

                await panel.set_brightness(PANEL_BRIGHTNESS)
                psutil.cpu_percent()
                await asyncio.sleep(0.5)
                first_frame = True
                while True:
                    animation = encode_status_animation(*read_status())
                    await panel.send_image_hex(animation, ".gif", save_slot=0)
                    if first_frame:
                        print("Panel potvrdil přenos animace (64 × 16 px).", flush=True)
                        first_frame = False
                    if once:
                        return 0
                    await asyncio.sleep(interval)
        except (BleakError, OSError, RuntimeError) as error:
            print(f"Přenos přes Bluetooth se nezdařil. {error}", file=sys.stderr, flush=True)
            if once:
                return 1
            print("Další pokus za 10 sekund. Ukončení pomocí Ctrl+C.", flush=True)
            await asyncio.sleep(10)


async def run(args):
    if args.preview is not None:
        psutil.cpu_percent()
        await asyncio.sleep(0.5)
        frame = render_status(*read_status())
        frame.resize((768, 192), Image.Resampling.NEAREST).save(args.preview)
        print(f"Náhled je uložený v {args.preview.resolve()}")
        return 0

    address = args.address.upper() if args.address else None
    if args.scan or address is None:
        print("Hledám LED panel přes Bluetooth LE…", flush=True)
        panels = await find_panels()
        if not panels:
            print("Panel jsem nenašel. Zkontroluj napájení a zavři aplikaci iPixel Color v telefonu.")
            return 1
        for index, (name, panel_address, rssi) in enumerate(panels, start=1):
            print(f"{index}. {name}  {panel_address}  ({rssi} dBm)")
        if args.scan:
            return 0
        try:
            choice = int(input("Číslo tvého panelu (0 = ukončit): "))
        except (ValueError, EOFError):
            print("Spusť program znovu a zadej číslo panelu ze seznamu.")
            return 1
        if choice == 0:
            return 0
        if not 1 <= choice <= len(panels):
            print("Zadané číslo v seznamu není.")
            return 1
        address = panels[choice - 1][1]

    return await show_status(address, args.interval, args.once)


def main():
    parser = argparse.ArgumentParser(description="Stavová obrazovka PC pro iPixel Color 64 × 16.")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--scan", action="store_true", help="Vyhledá LED panely.")
    modes.add_argument("--preview", type=Path, metavar="PNG", help="Uloží náhled bez Bluetooth.")
    modes.add_argument("--once", action="store_true", help="Odešle jednu animaci a skončí.")
    parser.add_argument("--address", help="Bluetooth adresa vlastního panelu AA:BB:CC:DD:EE:FF.")
    parser.add_argument("--interval", default=REFRESH_INTERVAL, type=int, metavar="SEKUNDY", help="Interval obnovy (výchozí %(default)s).")
    args = parser.parse_args()
    if args.interval < 1:
        parser.error("Interval musí být alespoň 1 sekunda.")
    if args.address and not re.fullmatch(ADDRESS_PATTERN, args.address):
        parser.error("Adresa musí mít formát AA:BB:CC:DD:EE:FF.")

    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 0
    except (BleakError, OSError) as error:
        print(f"Spuštění se nezdařilo. {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
