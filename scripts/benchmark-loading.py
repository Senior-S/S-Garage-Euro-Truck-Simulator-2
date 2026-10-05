"""Compare loading work with a repository revision using isolated cache folders."""
import argparse
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import assets
import saves


def baseline_module(name, revision, directory):
    """Load each original module from the same explicitly selected revision."""
    source = subprocess.check_output(["git", "show", f"{revision}:backend/{name}.py"], cwd=ROOT)
    path = directory / f"{name}.py"
    path.write_bytes(source)
    spec = importlib.util.spec_from_file_location(f"baseline_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def median_ms(task, rounds=5):
    """Use the same warmup and timing procedure for all CPU comparisons."""
    task()
    elapsed = []
    for _ in range(rounds):
        start = time.perf_counter()
        task()
        elapsed.append((time.perf_counter() - start) * 1000)
    return round(statistics.median(elapsed), 3)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, help="Trusted git revision to execute for comparison")
    parser.add_argument("--cache-root", required=True, type=Path, help="Folder for generated fixtures and isolated caches")
    parser.add_argument("--import-game", action="store_true", help="Also import installed game definitions twice; can take minutes")
    parser.add_argument("--model", action="append", type=Path, default=[], help="Existing PIM to compare without texture writes")
    args = parser.parse_args()
    directory = args.cache_root.resolve() / datetime.now().strftime("loading-%Y%m%d-%H%M%S-%f")
    directory.mkdir(parents=True)
    previous_assets = baseline_module("assets", args.baseline, directory)
    previous_saves = baseline_module("saves", args.baseline, directory)
    results = {"baseline": args.baseline, "synthetic": {}, "models": [], "catalog": {}}

    # A large owned fleet with attachment arrays, not unrelated padding units.
    trucks, parts = 200, 30
    chunks = [f"SiiNunit\n{{\nplayer : player {{\n trucks: {trucks}\n"]
    chunks.extend(f" trucks[{i}]: truck.{i}\n" for i in range(trucks))
    chunks.append("}\n")
    for i in range(trucks):
        chunks.append(f"vehicle : truck.{i} {{\n accessories: {parts}\n")
        chunks.extend(f" accessories[{j}]: part.{i}.{j}\n" for j in range(parts))
        chunks.append("}\n")
        for j in range(parts):
            category = "cabin" if j == 0 else "accessory/r_grill"
            chunks.append(f'vehicle_addon_accessory : part.{i}.{j} {{\n data_path: "/def/vehicle/truck/test/{category}/part{j}.sii"\n'
                          ' slot_name: 2\n slot_name[0]: "slot_0"\n slot_name[1]: "slot_1"\n'
                          ' slot_hookup: 2\n slot_hookup[0]: lamp\n slot_hookup[1]: lamp\n}\n')
    chunks.append("}\n")
    text = "".join(chunks)
    path = directory / "fixture.sii"
    path.write_text(text, encoding="utf-8")
    original = previous_saves.SaveSession(path, text, "test", "Test")
    current = saves.SaveSession(path, text, "test", "Test")
    assert original.state()["trucks"] == current.state()["trucks"]
    assert original.state()["truck"] == current.state()["truck"]
    catalog = [{"path": f"/part/{i}", "unitId": f"part.{i}", "unitName": f"part.{i}"} for i in range(30000)]
    for name, asset_module, save_module, session in (("baseline", previous_assets, previous_saves, original), ("optimized", assets, saves, current)):
        store = asset_module.AssetStore(cache_path=directory / name)
        store._catalog = catalog
        results["synthetic"][name] = {
            "stateMs": median_ms(session.state),
            "parseValidateMs": median_ms(lambda: save_module.SaveSession(path, text, "test", "Test")),
            "lookupMs": median_ms(lambda: [store.definition(f"/part/{i * 71}") for i in range(200)]),
        }
        print(name, results["synthetic"][name], flush=True)

    for model in args.model:
        comparison = {"file": model.name, "bytes": model.stat().st_size}
        parsed = []
        for name, module in (("baseline", previous_assets), ("optimized", assets)):
            # Texture URLs are deterministic placeholders; existing cache files stay untouched.
            with patch.object(module, "_texture_url", return_value="/texture.png"):
                start = time.perf_counter()
                parsed.append(module._parse_model(model, model.with_suffix(".pit"), directory))
                comparison[name + "Seconds"] = round(time.perf_counter() - start, 3)
        assert parsed[0] == parsed[1], "Model geometry/materials/locators changed"
        results["models"].append(comparison)
        print(comparison, flush=True)

    if args.import_game:
        imported = []
        for name, module in (("baseline", previous_assets), ("optimized", assets)):
            cache = directory / name
            start = time.perf_counter()
            entries = module.AssetStore(cache_path=cache).catalog()
            cold = time.perf_counter() - start
            start = time.perf_counter()
            reopened = module.AssetStore(cache_path=cache).catalog()
            warm = time.perf_counter() - start
            imported.append([(entry["path"], entry["fields"]) for entry in reopened])
            results["catalog"][name] = {"freshCacheSeconds": round(cold, 3), "warmCacheSeconds": round(warm, 3), "definitions": len(entries)}
            print(name, results["catalog"][name], flush=True)
        assert imported[0] == imported[1], "Imported definitions changed"

    result_path = directory / "results.json"
    result_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("Results:", result_path)
