"""Resolve saved dependencies and locally installed paint-only packages."""
from pathlib import Path
import json
import os
import re
import zipfile

from assets import _find_steam_roots, _library_paths
from saves import read_sii


def _truckersmp_sources() -> tuple[list[Path], list[str]]:
    """Find launcher-managed game assets, including custom installation paths."""
    roaming = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "TruckersMP"
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "TruckersMP"
    roots, issues = [], []
    options = roaming / "launcher-options.json"
    if options.is_file():
        try:
            configured = json.loads(options.read_text("utf-8-sig")).get("installPath")
            if isinstance(configured, str) and configured.strip():
                roots.append(Path(os.path.expandvars(configured)).expanduser())
        except (OSError, ValueError, AttributeError) as error:
            issues.append(f"Could not read TruckersMP launcher settings: {error}")
    roots.extend([roaming / "installation", Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "TruckersMP", local / "installation", local])
    for root in dict.fromkeys(roots):
        sources = []
        for game in ("shared", "ets2"):
            folder = root / "data" / game / "mods"
            try:
                if folder.is_dir():
                    sources.extend(sorted((path for path in folder.iterdir() if path.is_file() and path.suffix.casefold() in (".mp", ".scs", ".zip")), key=lambda path: path.name.casefold()))
            except OSError as error:
                issues.append(f"Could not inspect TruckersMP {game} assets: {error}")
        if sources:
            # Select one installation, rather than mixing old and current packs.
            return sources, issues
    return [], issues


def resolve_mods(save: Path, profiles_root: Path, game: Path | None, decryptor: Path | None) -> tuple[list[Path], list[str]]:
    info = save.parent / "info.sii"
    if info.is_file():
        text = read_sii(info, decryptor)
        dependencies = re.findall(r'^\s*dependencies\[\d+\]:\s*"([^"\r\n]+)"', text, re.M)
        tokens = [entry.split("|")[1] for entry in dependencies if entry.split("|")[0] in ("mod", "workshop") and "|" in entry]
    else:
        profile = save.parent.parent.parent / "profile.sii"
        tokens = re.findall(r'^\s*active_mods\[\d+\]:\s*"([^"\r\n]+)"', read_sii(profile, decryptor), re.M) if profile.is_file() else []
        tokens = [token.split("|")[0] for token in tokens]
    libraries = [library for steam in _find_steam_roots() for library in _library_paths(steam)]
    if game:
        libraries.insert(0, game.parent.parent.parent)
    workshop_roots = list(dict.fromkeys(library / "steamapps" / "workshop" / "content" / "227300" for library in libraries))
    mod_root = profiles_root.parent / "mod"
    sources, issues = _truckersmp_sources()
    # Unused paint jobs still belong in the catalog. Only auto-mount packages
    # whose vehicle definitions are all paint jobs, leaving other mods to the save.
    if mod_root.is_dir():
        candidates = [mod_root] + sorted(mod_root.iterdir(), key=lambda path: path.name.casefold())
        for candidate in candidates:
            try:
                if candidate.is_dir():
                    definitions = [path.relative_to(candidate).as_posix() for path in (candidate / "def").rglob("*")
                                   if path.is_file() and path.suffix.lower() in (".sii", ".sui")]
                elif candidate.suffix.lower() in (".scs", ".zip") and zipfile.is_zipfile(candidate):
                    with zipfile.ZipFile(candidate) as archive:
                        definitions = [name.replace("\\", "/").lstrip("/") for name in archive.namelist()
                                       if name.lower().startswith("def/") and name.lower().endswith((".sii", ".sui"))]
                else:
                    continue
                if definitions and all(re.fullmatch(r"def/vehicle/(?:truck|trailer_owned)/[^/]+/paint_job/.+\.(?:sii|sui)", name, re.I) for name in definitions):
                    sources.append(candidate)
            except (OSError, zipfile.BadZipFile) as error:
                issues.append(f"Could not inspect local paint mod {candidate.name}: {error}")
    # The mod manager stores highest priority first; later mounts override earlier ones.
    for token in reversed(tokens):
        if token.startswith("mod_workshop_package."):
            identifier = str(int(token.rsplit(".", 1)[1], 16))
            package = next((root / identifier for root in workshop_roots if (root / identifier).is_dir()), None)
            if package:
                versions = package / "versions.sii"
                names = re.findall(r'package_name:\s*"([^"\r\n]+)"', versions.read_text("utf-8")) if versions.is_file() else []
                candidates = [candidate for name in names for candidate in (package / name, package / f"{name}.zip", package / f"{name}.scs") if candidate.exists()]
                universal = [candidate for candidate in candidates if candidate.stem == "universal"]
                if universal:
                    sources.extend(universal[:1])
                elif len(candidates) == 1:
                    sources.extend(candidates)
                else:
                    issues.append(f"Workshop mod {token}: version-specific package selection is required. Its assets were omitted.")
                continue
        else:
            path = next((candidate for candidate in (mod_root / token, mod_root / f"{token}.scs", mod_root / f"{token}.zip") if candidate.exists()), None)
            if path and path.resolve().is_relative_to(mod_root.resolve()):
                # A saved package keeps its actual load priority, even if it was
                # already discovered as an available paint job.
                sources = [source for source in sources if source.resolve() != path.resolve()]
                sources.append(path)
                continue
        issues.append(f"Saved mod {token} could not be found locally. Its saved parts are preserved.")
    return sources, issues
