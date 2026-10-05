"""Compare complete fresh and cached catalog imports through the garage backend."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.assets import AssetStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--game", type=Path)
    parser.add_argument("--cache-root", type=Path, default=Path("E:/ETS2-Garage/benchmarks"))
    parser.add_argument("--repeats", type=int, default=1)
    options = parser.parse_args()
    if options.repeats < 1:
        parser.error("--repeats must be positive")
    if not options.cache_root.resolve().is_relative_to(Path("E:/ETS2-Garage").resolve()):
        parser.error("Cache runs must stay under E:\\ETS2-Garage")
    options.cache_root.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="converter-cache-", dir=options.cache_root))
    for name in ("TEMP", "TMP"):
        os.environ[name] = str(folder)
    results = {"cacheConditions": "New output directories with normal Windows filesystem caches; not cold HDD",
               "assetsSha256": hashlib.sha256(Path(sys.modules[AssetStore.__module__].__file__).read_bytes()).hexdigest(),
               "records": [], "complete": False}
    try:
        for repeat in range(options.repeats):
            hashes = {}
            for name in (("baseline", "candidate") if repeat % 2 == 0 else ("candidate", "baseline")):
                cache = folder / f"{repeat}-{name}"
                store = AssetStore(game_path=str(options.game) if options.game else None, cache_path=cache)
                store.tool_path = getattr(options, name).resolve()
                if not store.status()["ready"]:
                    raise RuntimeError(store.status()["message"])
                started = time.perf_counter()
                catalog = store.catalog()
                fresh = time.perf_counter() - started
                hashes[name] = hashlib.sha256(json.dumps(catalog, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                reopened = AssetStore(game_path=str(store.game_path), cache_path=cache)
                reopened.tool_path = store.tool_path
                started = time.perf_counter()
                cached = reopened.catalog()
                warm = time.perf_counter() - started
                if catalog != cached:
                    raise AssertionError(f"{name} cached catalog differs from fresh import")
                files = [file for file in cache.rglob("*") if file.is_file()]
                results["records"].append({"implementation": name, "repeat": repeat,
                    "executable": str(store.tool_path), "executableSha256": hashlib.sha256(store.tool_path.read_bytes()).hexdigest(),
                    "game": str(store.game_path), "archiveCount": len(store._archives()),
                    "freshSeconds": fresh, "cachedSeconds": warm, "definitions": len(catalog), "catalogSha256": hashes[name],
                    "cacheFileCount": len(files), "cacheBytes": sum(file.stat().st_size for file in files), "cachePath": str(cache)})
                print(f"{name}: fresh {fresh:.3f}s, cached {warm:.3f}s, {len(catalog)} definitions, {len(files)} files", flush=True)
            if hashes["baseline"] != hashes["candidate"]:
                raise AssertionError("Baseline and candidate catalogs differ")
        results["medians"] = {name: {key: statistics.median(record[key] for record in results["records"] if record["implementation"] == name)
                                    for key in ("freshSeconds", "cachedSeconds", "cacheFileCount", "cacheBytes")}
                              for name in ("baseline", "candidate")}
        results["complete"] = True
    finally:
        destination = folder / "results.json"
        destination.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"Results: {destination}", flush=True)


if __name__ == "__main__":
    main()
