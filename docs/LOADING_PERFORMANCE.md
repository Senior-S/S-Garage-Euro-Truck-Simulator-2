# Loading review

This review compares `optimizations` with `b99879ee802f95f04eb0b85f5017cd39895da117`, the starting commit on `trailers`.

## Changes applied

| Loading path | Finding | Change |
| --- | --- | --- |
| First launch | The app imported base definitions before the user chose a save. A modded save could then require another full import. | Resolve the save's mod sources first. Show the UI immediately and import the catalog when a save is selected. |
| Browser startup | Three.js and both preview renderers loaded before any vehicle was selected. | Load the garage and catalog renderers on demand. Keep queue/cache helpers in a small module. Import only the color utility needed by the initial UI. |
| Catalog concurrency | Requests checked the in-memory catalog before waiting for the import lock, allowing a waiting request to repeat an import. | Check again after acquiring the lock. Concurrent requests share the completed catalog. |
| Catalog persistence | An interrupted JSON write could leave a cache that failed on the next launch. | Write through a temporary file, replace the index, and rebuild malformed indexes. Publish the in-memory catalog after a successful write. |
| Catalog responses | Every request recomputed duplicate signatures for the full catalog. | Reuse the prepared response until the source catalog changes. |
| Definition lookup | Every model/paint lookup scanned the full catalog. | Build a case-insensitive index once per catalog, preserving the last source's priority. |
| Save selection | Loading one save opened the headers of every save again. | Validate and resolve the selected save directly within the configured profile root. |
| Save reads | Reading/decrypting, hashing, and checking the BOM read the source separately. | Reuse one source snapshot. External-write checks still compare against that snapshot before saving. |
| Save parsing | Attachment arrays parsed the same fields repeatedly; every vehicle built full attachment state even though only one was shown. | Reuse parsed fields and build full accessory/attachment output for the selected vehicle. |
| Model parsing | Block extraction walked large numeric streams character by character. Part metadata was parsed repeatedly, and shadow-only geometry was parsed before being discarded. | Scan delimiters directly, reuse part metadata, and skip shadow-only streams before numeric parsing. |
| Mod directories | Fingerprinting checked the directory type repeatedly and requested file metadata twice. | Check each source type once and each file's metadata once. Report file counts during this stage. |
| Converter calls | Readiness checks generated an unused preview fingerprint and rescanned archives. Model imports also calculated the same fingerprint repeatedly. | Use one archive list per converter call and one fingerprint per model import. |
| Preview contention | Catalog thumbnail and hover imports competed with the selected vehicle. | Pause and cancel those previews while opening saves or preparing vehicle geometry. Resume when loading finishes. |

Serial conversion remains in place so several imports do not seek around a hard disk simultaneously. Existing game/DLC/mod mounting order is preserved.

## Progress UX

Loading jobs have request IDs and report to `/api/progress`. This endpoint takes neither the garage lock nor the asset import lock. A slow converter or save load therefore does not stop progress polling.

The inline panel shows the current stage, a short description, elapsed time, and actual completed/total counts during definition indexing, mod checks, and fitted-part loading. Work with an unknown total uses an indeterminate bar. Percentages and time-to-completion estimates are not invented. Polling stops when requests finish or are cancelled, retries after connection interruptions, and cannot accumulate overlapping polls.

The welcome guide shows the same progress component during the first visit. On narrow windows, loading feedback stays above the floating catalog. Stage labels are announced to assistive technology, and the indeterminate bar respects reduced motion.

The progress tracker and React component are shared because catalog import, save loading, and scene assembly need the same reporting and cleanup. The thumbnail storage helper keeps Cache Storage access independent of WebGL code.

## Measurements

Measured locally on Windows with Python 3.13. These are individual stages, not a promise about total loading time on another machine.

| Work | Before | After | Input |
| --- | ---: | ---: | --- |
| Initial JavaScript | 732.8 KB | 217.1 KB | Production Vite build, uncompressed; 3D chunks load when needed |
| Selected vehicle state | 375.9 ms | 65.3 ms | Synthetic fleet of 200 trucks and 6,000 parts, median of 5 runs |
| Save parse and validation | 372.7 ms | 177.6 ms | Same 1.56 MB synthetic save, median of 5 runs |
| 200 definition lookups | 1,663.9 ms | 0.112 ms | 30,000 synthetic catalog entries, median of 5 runs after index warmup |
| Chassis model parsing | 12.57 s | 5.89 s | Real cached 20.9 MiB PIM; texture conversion excluded |
| Trailer model parsing | 9.69 s | 4.62 s | Real cached 16.1 MiB PIM; texture conversion excluded |
| Definition indexing | 27.37 s | 23.84 s | Same extracted game definitions, 61,534 entries |
| Cached catalog read | 1.43 s | 1.15 s | Actual installed game, separate cache folders |

Both real model comparisons produced identical geometry, material metadata, and locators. Catalog comparisons produced identical definitions. A further 2,000 randomized brace, quote, and escape cases matched the original block parsers.

A preliminary fresh-cache run, before the final delimiter-scanning changes, took 124.3 s for the baseline and 131.9 s for the optimized importer. Raw archive extraction remains expensive; that measurement does not support a claim of faster extraction. Runs used separate cache directories under `E:\ETS2-Garage\benchmarks`, but did not clear Windows' filesystem caches or isolate other disk activity. The initial UI now avoids this work until a save is chosen, and a modded save avoids importing an unused base-only catalog first.

The configured application cache is `E:\ETS2-Garage\cache`. Settings remain in LocalAppData. Benchmark caches are separate, and no real game or save files were written during these checks.

## Reproduce and verify

```powershell
python scripts/benchmark-loading.py --baseline b99879ee802f95f04eb0b85f5017cd39895da117 --cache-root E:\ETS2-Garage\benchmarks
python -m unittest discover -s tests -v
cd ui
node --test tests/*.test.js
npm run build
```

Add `--model <existing.pim>` to compare a real exported model without converting textures. Add `--import-game` to compare fresh and cached catalogs using the installed game. This can take several minutes. Each run creates its own folder and saves `results.json`; existing caches stay intact. The baseline argument executes source from the selected git revision, so use a trusted revision.

Browser checks used an isolated server and temporary saves. They verified deferred script loading, stage/count updates, progress visibility at 1280 and 390 pixels, completion cleanup, WebGL viewer loading, and thumbnail generation. HTTP regressions cover progress while import/session locks are held, request isolation, interrupted cache recovery, selected-save path validation, and preservation of external-save conflict detection.

## Remaining costs

ConverterPIX still mounts archives for each uncached model conversion and exports definitions to many small files. Its pinned command interface handles one model per invocation; batching through repeated `-m` flags would not work. Changing that requires converter support or a separate archive reader, rather than a change to the existing queue. See [ConverterPIX's command implementation](https://github.com/mwl4/ConverterPIX/blob/3cd4e73a86d0c6bd28e117664c50a36cabeccf38/src/cmd/_main.cpp).

The model parser fingerprint changes with importer updates. Existing complete converter exports remain reusable, but parsed model JSON may need to be regenerated once. Full uncached scene loading still depends on archive access, texture decoding, and the number of fitted parts. End-to-end cold loading on a dedicated hard disk has not been measured.
