"""Bounded, unauthenticated checks for published S Garage releases."""
import json
from pathlib import Path
import re
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen


REPOSITORY = "Senior-S/S-Garage-Euro-Truck-Simulator-2"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
VERSION = (Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])) / "VERSION").read_text("utf-8").strip()


def check_updates() -> dict:
    """Try once plus three retries, with a five-second timeout per request."""
    result = {"currentVersion": VERSION, "status": "unavailable", "url": RELEASES_URL}
    request = Request(f"https://api.github.com/repos/{REPOSITORY}/releases/latest", headers={
        "Accept": "application/vnd.github+json", "User-Agent": f"S-Garage/{VERSION}",
        "X-GitHub-Api-Version": "2022-11-28"})
    for attempt in range(4):
        try:
            with urlopen(request, timeout=5) as response:
                release = json.load(response)
            tag = release["tag_name"]
            latest = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", tag)
            current = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", VERSION)
            if not latest or not current or release.get("draft") or release.get("prerelease"):
                raise ValueError("Not a stable release version")
            newer = tuple(map(int, latest.groups())) > tuple(map(int, current.groups()))
            return {**result, "status": "available" if newer else "current", "latestVersion": tag.lstrip("v")}
        except (URLError, OSError, ValueError, KeyError, TypeError):
            if attempt < 3:
                time.sleep(.5 * 2 ** attempt)
    return result
