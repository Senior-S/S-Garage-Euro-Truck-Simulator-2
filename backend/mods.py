"""Resolve saved mod dependencies without mounting unrelated installed mods."""
from pathlib import Path
import re

from assets import _find_steam_roots, _library_paths
from saves import read_sii


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
    sources, issues = [], []
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
                sources.append(path)
                continue
        issues.append(f"Saved mod {token} could not be found locally. Its saved parts are preserved.")
    return sources, issues
