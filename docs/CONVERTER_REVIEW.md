# ConverterPIX review

Reviewed upstream revision `3cd4e73a86d0c6bd28e117664c50a36cabeccf38`, also the garage's pinned version. Upstream HEAD matched this revision on 2026-10-04.

The subsequent [fork implementation and measurements](CONVERTER_FORK.md) use `Senior-S/ConverterPIX-SGarage`, cloned beside the garage source. The remainder of this document records the earlier review and prototype.

A separate local checkout is at `E:\ETS2-Garage\ConverterPIX`, on branch `garage-optimizations`. This is a local fork candidate, not a published GitHub fork. The garage still uses its original pinned executable. No garage servers were started during this review.

## Findings and priorities

| Priority | Finding | Proposed change | Limits and validation |
| --- | --- | --- | --- |
| 1 | `EXTRACT_DIRECTORY` enumerates files and writes each separately. The garage then opens these files to build its JSON catalog. | Add an optional bundle extraction mode with path, length, and raw file bytes. Let the garage build its catalog from that bundle. | This targets HDD metadata and seek costs. Preserve include resolution, source paths, external definition references, and last-mounted mod priority. Keep the existing extraction mode. |
| 1 | `Model::saveToPim` formats vertex streams as text. Python parses that text into arrays and serializes geometry again. | Add a garage geometry export alongside the existing PIM/PIT exporters. Use typed binary arrays and a small metadata manifest for materials, parts, variants, and locators. | Likely the strongest model-loading improvement, but not benchmarked. Must preserve UV sets, transforms, material aliases, looks, variants, and textures. Browser and backend changes are required. |
| 2 | `main` mounts every supplied archive on every invocation. `HashFsV2::readHashFS` reads and decompresses archive entry and metadata tables again. | Add a manifest batch mode first, with model/texture path and output folder per job. Consider a persistent serial worker if interactive requests still spend meaningful time mounting. | Warm mounting/process overhead measured about 0.13–0.17 seconds across 114 installed archives. This is cumulative, but does not explain multi-second Python model parsing. Cold HDD costs remain unmeasured. A worker needs archive/mod invalidation, bounded resource caching, cancellation, and per-job failures. |
| 2 | Directory entries already carry a source filesystem, but extraction calls `extractFile(*getUFS(), ...)`, searching archives again. | Investigate a direct source open for resolved entries, or cache archive resolution in the mounted filesystem. | Must retain overlay and failure semantics, including higher-priority files masking lower-priority entries. Do not simply assume every directory listing is equivalent to an open lookup for malformed mods. |
| 2 | `Model::load` loads collision and prefab data. `saveToMidFormat` also writes PIS/PIC/PIP. The garage's preview parser consumes PIM/PIT. | Add an explicit garage preview mode that avoids unused auxiliary loads and exports. | Audit skeleton/locator dependencies before skipping anything. Keep full conversion as the default. |
| 3 | `copyFile` allocates and frees a 10 MiB buffer for every copied file. | Reuse the same scratch allocation per thread. | Implemented in the local branch, with unchanged copy chunk size. It retains 10 MiB per thread that performs copies until thread exit. |
| 3 | `UberFileSystem::readDir` uses an ordered map to deduplicate paths and recursively copies directory entries. | Benchmark hash-set deduplication and append-based traversal. | These are CPU/allocation improvements, not a substitute for fewer disk operations. Keep traversal/output ordering where observable. |
| 3 | Zlib reads use 4 KiB compressed chunks. GDeflate decompression uses one worker. | Benchmark larger compressed buffers and bounded decompression workers for large resources. | Tiny definitions may not benefit. Archive reads share seekable file handles, so parallel extraction is not currently safe without changes to archive I/O. Unbounded concurrency can increase HDD seeks. |

## Prototype and measurements

The local branch changes only the existing `copyFile` helper and CLI timing. No new C++ methods were needed. A lazy thread-local heap buffer replaces repeated allocations. `--show-elapsed-time` now also reports mounting time separately; upstream's existing elapsed timer starts after mounting.

Both unchanged and patched sources built with Visual Studio 2026, Release x64, overriding the old project toolset and SDK:

```powershell
& 'F:\Program Files\Microsoft Visual Studio\2026\MSBuild\Current\Bin\MSBuild.exe' src\ConverterPIX.sln /m /p:Configuration=Release /p:Platform=x64 /p:PlatformToolset=v145 /p:WindowsTargetPlatformVersion=10.0 /verbosity:quiet /nologo
```

Existing source conversion warnings and an MSVCRT/static-runtime linker warning remain. The build is suitable for the local experiment; release distribution needs a clean dependency/runtime build. Save the unchanged build as `bin\win_x64\converter_pix_baseline.exe` before building the patch.

The reproducible local script `E:\ETS2-Garage\ConverterPIX\scripts\benchmark-extraction.py` alternates both builds over three runs each and checks SHA-256 equality of every extracted file. Inputs are the installed game's 114 archives and `/def/vehicle/truck/scania.s_2016`, containing 3,842 files. Outputs stay under `E:\ETS2-Garage\benchmarks`.

These runs use Windows filesystem caches and newly created output directories. They do not establish a dedicated cold-HDD result. The final prototype's median was 2.183 seconds unchanged versus 2.082 seconds patched, approximately 4.6% less time, with identical output. This is a modest gain and includes filesystem variability. Detailed run data is at `E:\ETS2-Garage\benchmarks\converter-review-e520261b\results.json`.

Additional comparisons cover empty files, a tiny file, an 11 MiB file spanning copy chunks, and a ZIP mod overriding a base archive. Expected output bytes matched both builds. The scratch-buffer change preserves upstream's existing read/write error handling; that handling should be hardened before a persistent worker is introduced.

## Recommended fork scope

Keep upstream's C++ decoders and default CLI behavior. Start with profiling and optional bundle extraction, then implement direct geometry export. Add batching if repeated mount costs are material for a complete fitted truck. This avoids rewriting working binary-format support and targets the expensive data transfers between the converter, disk, Python, and the browser.

Batching must account for `ResourceLibrary` caching texture objects and `TextureObject::saveToMidFormats` skipping objects marked converted. The garage currently uses separate output directories for each model. Reusing these objects across jobs without resetting conversion state or tracking output destinations could leave later jobs without textures. A common shared texture cache is a separate design change, not an automatic benefit of keeping the process alive.

All larger gains above are hypotheses until tested with equivalent output and complete scene loading. A fork's distributed executable must retain upstream licensing and ship corresponding modified source, following the project's existing third-party-source packaging approach.

## Source references

- [CLI modes, mounting, timer, extraction loop](https://github.com/mwl4/ConverterPIX/blob/3cd4e73a86d0c6bd28e117664c50a36cabeccf38/src/cmd/_main.cpp)
- [Archive priority, open lookup, directory merging](https://github.com/mwl4/ConverterPIX/blob/3cd4e73a86d0c6bd28e117664c50a36cabeccf38/src/fs/uberfilesystem.cpp)
- [HashFS v2 mounting and entry lookup](https://github.com/mwl4/ConverterPIX/blob/3cd4e73a86d0c6bd28e117664c50a36cabeccf38/src/fs/hashfs_v2.cpp)
- [File copying](https://github.com/mwl4/ConverterPIX/blob/3cd4e73a86d0c6bd28e117664c50a36cabeccf38/src/fs/file.cpp)
- [Model loading and PIM/export code](https://github.com/mwl4/ConverterPIX/blob/3cd4e73a86d0c6bd28e117664c50a36cabeccf38/src/model/model.cpp)
