import io
import json
import math
import os
import unicodedata
import xml.etree.ElementTree as xml
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from html import unescape
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from PIL import Image, ImageDraw, ImageFont
from pypixelcolor.lib.emoji_manager import is_emoji
from pypixelcolor.lib.font_config import FontConfig

from pc_status import PANEL_SIZE
from windows_http import get

WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
NEWS_URL = "https://api-web.novinky.cz/v1/timelines/62f1fae17dfc203ce39d48ca?xml=rss"
WEATHER_SOURCE = "https://open-meteo.com/"
NEWS_SOURCE = "https://www.novinky.cz/p/tiraz"
USER_AGENT = "LED-Panel-PC/1.2 (+https://github.com/Takashiri/led-panel-pc)"
FONT_PATH = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeuib.ttf"
NEWS_FONT_SIZE = 13
NEWS_COLOR = "e8f4ff"
NEWS_SPEED = 50


class Page(Enum):
    PC = "Stav PC"
    WEATHER = "Počasí"
    NEWS = "Novinky.cz"


@dataclass(frozen=True)
class Location:
    name: str
    label: str
    latitude: float
    longitude: float

    @classmethod
    def from_mapping(cls, data):
        if not isinstance(data, dict):
            return None
        try:
            name, label = data["name"], data["label"]
            latitude, longitude = float(data["latitude"]), float(data["longitude"])
        except (KeyError, TypeError, ValueError):
            return None
        if not isinstance(name, str) or not isinstance(label, str) or not name.strip() or not label.strip():
            return None
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return None
        return cls(name, label, latitude, longitude)


@dataclass(frozen=True)
class Weather:
    temperature: int
    humidity: int


@dataclass(frozen=True)
class Headline:
    title: str
    url: str

    @property
    def ticker(self):
        # The device library would otherwise fetch graphics for emoji it detects.
        text = "".join(char for char in panel_text(self.title) if not is_emoji(char))
        text = " ".join(text.split())
        if len(text) > 180:
            text = text[:177].rsplit(" ", 1)[0] + "…"
        return f"Novinky.cz  •  {text}"


def fetch(url, params=None):
    if params is not None:
        url = f"{url}?{urlencode(params)}"
    return get(url, USER_AGENT)


def find_locations(query):
    data = json.loads(fetch(GEOCODING_URL, {"name": query, "count": 8, "language": "cs"}))
    locations = []
    for row in data.get("results", []):
        label = ", ".join(dict.fromkeys(row[key] for key in ("name", "admin1", "country") if row.get(key)))
        location = Location.from_mapping({**row, "label": label})
        if location is not None:
            locations.append(location)
    return locations


def read_weather(location):
    data = json.loads(fetch(WEATHER_URL, {
        "latitude": location.latitude,
        "longitude": location.longitude,
        "current": "temperature_2m,relative_humidity_2m",
        "temperature_unit": "celsius",
    }))["current"]
    temperature = data.get("temperature_2m")
    humidity = data.get("relative_humidity_2m")
    if not isinstance(temperature, (int, float)) or not math.isfinite(temperature):
        raise ValueError("Zdroj neposkytl platnou teplotu.")
    if not isinstance(humidity, (int, float)) or not 0 <= humidity <= 100:
        raise ValueError("Zdroj neposkytl platnou vlhkost.")
    return Weather(round(temperature), round(humidity))


def read_headline():
    root = xml.fromstring(fetch(NEWS_URL))
    for item in root.findall("./channel/item"):
        title = " ".join(unescape(item.findtext("title", "")).split())
        link = item.findtext("link", "").strip()
        parts = urlsplit(link)
        if title and parts.scheme == "https" and parts.hostname in {"www.novinky.cz", "novinky.cz"}:
            return Headline(title, link)
    raise ValueError("RSS kanál neobsahuje dostupnou zprávu.")


def font(size):
    return ImageFont.truetype(str(FONT_PATH), size)


def pixel_draw(image):
    draw = ImageDraw.Draw(image)
    draw.fontmode = "1"
    return draw


def panel_text(text):
    return "".join(char for char in unicodedata.normalize("NFD", text) if not unicodedata.combining(char))


def centered(draw, text, bounds, size, color):
    left, top, width, height = bounds
    text = panel_text(text)
    face = font(size)
    if draw.textlength(text, font=face) > width:
        while text and draw.textlength(text + "…", font=face) > width:
            text = text[:-1]
        text += "…"
    x0, y0, x1, y1 = draw.textbbox((0, 0), text, font=face)
    draw.text((left + (width - (x1 - x0)) // 2 - x0, top + (height - (y1 - y0)) // 2 - y0),
              text, font=face, fill=color)


def render_weather(location, weather, message):
    frame = Image.new("RGB", PANEL_SIZE)
    draw = pixel_draw(frame)
    centered(draw, location.name if location else "Počasí", (2, 0, 60, 7), 8, "#d4e4f2")
    if weather is None:
        centered(draw, message, (2, 7, 60, 9), 8, "#f1be74")
    else:
        draw.line((32, 8, 32, 15), fill="#35495e")
        centered(draw, f"{weather.temperature}°C", (0, 7, 32, 9), 11, "#7addfb")
        draw.polygon(((36, 9), (34, 12), (34, 14), (38, 14), (38, 12)), fill="#8fea83")
        centered(draw, f"{weather.humidity}%", (39, 7, 25, 9), 9, "#8fea83")
    return frame


@lru_cache(maxsize=8)
def news_strip(text):
    face = font(NEWS_FONT_SIZE)
    width = math.ceil(face.getlength(text))
    strip = Image.new("RGB", (width + PANEL_SIZE[0], PANEL_SIZE[1]))
    pixel_draw(strip).text((0, 0), text, fill=f"#{NEWS_COLOR}", font=face)
    return strip


def render_news(headline, message, offset=0):
    if headline:
        strip = news_strip(headline.ticker)
        start = offset % strip.width
        frame = Image.new("RGB", PANEL_SIZE)
        frame.paste(strip, (-start, 0))
        if start + PANEL_SIZE[0] > strip.width:
            frame.paste(strip, (strip.width - start, 0))
        return frame
    frame = Image.new("RGB", PANEL_SIZE)
    draw = pixel_draw(frame)
    centered(draw, "Novinky.cz", (2, 0, 60, 7), 8, "#d4e4f2")
    centered(draw, message, (2, 7, 60, 9), 8, "#f1be74")
    return frame


def png_hex(frame):
    with io.BytesIO() as buffer:
        frame.save(buffer, format="PNG")
        return buffer.getvalue().hex()


def ticker_font():
    return FontConfig.from_file(FONT_PATH, font_size=NEWS_FONT_SIZE, var_width=True, pixel_threshold=128)
