# ConverterPIX garage fork

The [ConverterPIX-SGarage fork](https://github.com/Senior-S/ConverterPIX-SGarage) retains upstream decoders and adds optional exports for the garage. Setup and release packaging use fork commit `ce70713952c93adafd651feb5b64e1078010b1d4`, based on upstream `3cd4e73a86d0c6bd28e117664c50a36cabeccf38`. The local source checkout is `E:\Dev Stuff\ETS2\ConverterPIX-SGarage`; its format docs and validation scripts remain local and Git-ignored. See [the original review](CONVERTER_REVIEW.md) for the earlier buffer experiment.

## Implemented changes

- Definition import writes one binary bundle containing virtual paths and original bytes. The garage indexes that file and reads paint/physics includes by offset, preserving mod mount priority and external include extraction.
- Viewer export writes a small `.sgm` manifest and little-endian `.sgb` arrays. The garage reads those arrays directly and shares its existing PIT material, look, variant, and attachment handling with the PIM path. The viewer receives the same model response.
- TSV batch jobs mount the game, DLC, and selected mod archives once. The garage batches missing fitted models and referenced hookups, deduplicates shared model paths, and reuses complete exports and parsed caches. Jobs run serially and report individual success or failure.
- Explicit garage preview mode skips collision, prefab, and auxiliary exports. Skeleton metadata remains available in the native format. Normal conversion still produces the upstream formats.
- The existing copy helper reuses one lazy 10 MiB scratch allocation per copying thread. Bundle extraction reuses a buffer sized to the largest entry, reading each entry in one call because HashFS v2 GDeflate requires that. Read/write failures propagate to job results.

`ResourceLibrary` is cleared between jobs so a texture marked converted for one output directory cannot disappear from another. Bundles publish through a checked temporary file and atomic replacement. Native manifests publish after their geometry, PIT, and loaded textures finish. Failed or cancelled garage batches retain incomplete markers; successful models stay reusable.

The capability probe checks `--help` before requesting garage-specific JSON, so the original executable remains usable. Executable path, size, and modification time invalidate the probe result. Parser fingerprints cover both the asset importer and the format readers. The Windows packaging script includes both source files for that fingerprint.

When the selected converter supports bundled definitions and native geometry, startup detects loose catalog exports or cached PIM models and requires acceptance of a cache rebuild notice before loading assets. Acceptance deletes only the managed `catalog` and `models` cache trees and browser thumbnails, then imports a fresh catalog with progress. Saves, settings, and other cache-root files remain intact. Models rebuild on demand. Failed rebuilds keep the notice open with a retry action; empty and native-only caches do not prompt.

New C++ methods follow the existing exporter pattern or isolate the bundle's I/O lifecycle. New Python helpers share model selection/cache paths between single and batch imports, and share bundle-aware definition reads between catalog, paint, and physics loading. The format readers centralize checks for repeated binary descriptors and metadata.

## Measurements

Both upstream and fork sources built in Release x64 with Visual Studio 2026, `v145`, and the Windows 10 SDK. Measurements used the installed game's 114 archives, new output directories, and normal Windows filesystem caches. They do not establish a dedicated cold-HDD result.

The following values are medians of three alternating runs. Converter time includes process startup, archive mounting, and texture export. Parse time includes the garage parser and texture preparation, excluding final model JSON serialization and HTTP/browser work.

| Work | Upstream | Fork |
| --- | ---: | ---: |
| Extract 3,842 Scania definition files | 2.213 s | 0.273 s |
| Reopen and hash those definition bytes | 0.913 s | 0.021 s |
| Scania chassis conversion | 0.318 s | 0.200 s |
| Scania chassis parsing | 2.570 s | 0.087 s |
| Trailer chassis conversion | 0.284 s | 0.218 s |
| Trailer chassis parsing | 1.476 s | 0.046 s |
| Skinned interior conversion | 0.305 s | 0.250 s |
| Skinned interior parsing | 1.065 s | 0.294 s |
| Small grille accessory conversion | 0.181 s | 0.189 s |
| Small grille accessory parsing | 0.034 s | 0.003 s |

The tiny accessory's conversion was slightly slower in this run. Its combined conversion and parsing still fell from 0.215 s to 0.191 s. Larger models gain mostly from removing text geometry. Combined Scania chassis conversion and parsing fell from 2.881 s to 0.287 s, and trailer chassis from 1.759 s to 0.264 s. These combined figures are medians of each run's sum.

The definition sample contains 4,387,427 raw bytes. Per-file extraction writes 3,842 files; the bundle writes one 4,677,353-byte file, including record framing. Warm process/mount probes stayed approximately 0.145 s for both builds, which supports batching several jobs rather than expecting a faster archive mount implementation.

A separate complete catalog comparison ran once per build through `AssetStore.catalog()`, using separate caches. Both produced identical 61,534-entry catalogs and identical reopened catalogs.

| Complete catalog import | Upstream | Fork |
| --- | ---: | ---: |
| Fresh cache | 108.029 s | 21.448 s |
| Reopen cached catalog | 1.153 s | 1.197 s |
| Cache files | 100,771 | 2 |

Fresh import took about 80% less time in this run. Cached reopening was essentially unchanged because both paths reuse `catalog.json`. This single comparison still used Windows filesystem caches. Its records are at `E:\ETS2-Garage\benchmarks\converter-cache-zibx8gi2\results.json`.

The reviewed fork executable's SHA-256 is `3eb6104eb8b24edb48a5e90e55d196849861d1e0d4302e7354036bc7e7ec5b9c`. Detailed records, logs, outputs, and frozen executables are under `E:\ETS2-Garage\benchmarks\converter-fork-20261004-195315-028`. The main measurement file is `run-3\results.json`.

## Verification

The main benchmark passed 29 checks. All three repeats matched definition names and SHA-256 hashes, raw mesh stream values, triangle winding, PIT bytes, and parsed viewer results. Comparisons include selected looks/variants, multiple UV sets and aliases, part membership, hidden locators, material aliases/effects, textures, and a 51-bone interior. Native row-major matrices match PIS after transposing its layout. Skin indices and weights match exactly.

A separate resource bundle check matched 21 real chassis files totaling 15,292,661 bytes, with a largest entry of 3,114,828 bytes. Synthetic coverage includes empty entries, nested paths, ZIP mod overrides, an 11 MiB compressed payload, corrupt archive reads, failed writes, malformed batches, failure continuation, independent output directories, and removal of stale native manifests. All 26 focused CLI cases passed.

The garage suite covers bundled and loose catalog equality, Windows filename case handling, bundle-only paint settings/overrides, shared physics includes, native/PIM equivalence, batch cache reuse, per-job failures, cancellation, selected scene requests, and safe upstream capability probing. All 97 tests pass, including existing save, server, and scene regressions.

The build retains upstream conversion warnings and the existing MSVCRT/static-runtime linker warning. Distributed fork releases still need a consistent dependency/runtime build and a pinned executable paired with its corresponding modified source archive. Current garage release inputs continue to use upstream.

## Reproduce

Build and select the fork with `./scripts/build-converter-fork.ps1`, or choose its executable in Settings. The helper accepts source, MSBuild, and toolset overrides. See [development setup](DEVELOPMENT.md#tool-sources).

```powershell
$run = 'E:\ETS2-Garage\benchmarks\converter-fork-20261004-195315-028'
python ../ConverterPIX-SGarage/scripts/benchmark-garage.py --baseline "$run/baseline.exe" --candidate "$run/candidate-reviewed.exe" --garage-repo . --run-folder E:/ETS2-Garage/benchmarks/new-converter-run --repeats 3
python ../ConverterPIX-SGarage/scripts/check-garage-cli.py --baseline "$run/baseline.exe" --converter "$run/candidate-reviewed.exe" --output E:/ETS2-Garage/benchmarks/new-cli-run
python scripts/benchmark-converter-cache.py --baseline "$run/baseline.exe" --candidate "$run/candidate-reviewed.exe"
$env:TEMP = 'E:\ETS2-Garage'
$env:TMP = $env:TEMP
python -m unittest discover -s tests -v
```

Use fresh output folders. Benchmark scripts keep runs under `E:\ETS2-Garage` and do not clear Windows' filesystem caches. The catalog benchmark measures the complete backend import and reopening path, with catalog equality checked between builds.
