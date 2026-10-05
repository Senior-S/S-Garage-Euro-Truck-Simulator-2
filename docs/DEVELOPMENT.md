# Technical notes: S Garage

S Garage opens an ETS2 save, lists its owned trucks, and builds a garage preview from the user's installed game assets. You can swap parts across brands, add or duplicate accessory instances, edit instance fields, and assign multiple hookups to model attachment points. Edits support undo and redo. Saving creates a backup and writes the truck back into the loaded save.

This is an initial working application. The preview uses actual game geometry and attachment locators. Browser materials approximate the game's shaders. It needs further in-game comparison before it can promise that every combination looks exactly as it does in ETS2.

For portable Windows downloads, see [Installation](INSTALLATION.md). These notes describe the source launcher and implementation.

## Open the source app

Double-click **Start Garage.cmd** in this folder. It starts the Python server in the background and opens `http://127.0.0.1:8765`. **Stop Garage.cmd** stops that server. Closing the browser keeps the server and editing session available until you stop it. Save your changes before stopping the server. Browser windows share one editing session; stale windows must reload before editing.

Requirements for a source checkout are Windows x64, Python 3.10 or newer, and Node.js 20 or newer for the first UI build. The launcher installs Pillow, builds the UI if necessary, and downloads pinned ConverterPIX-SGarage and SII Decrypt binaries if missing. SHA-256 checks verify existing and newly installed tools. Once the UI, fonts, and tools are installed, the app runs locally without fetching web assets.

Steam's registry entries and `libraryfolders.vdf` locate the game, including libraries on other drives. Windows' Documents location finds the profiles. Settings accepts overrides for the game folder, profiles folder, converter, and decryptor. The app also checks `steam_profiles` alongside `profiles`.

## Edit a truck

1. Choose a profile, then a save from that profile. Saves show their dates and list newest modified first. Choose an owned truck.
2. Orbit with a drag and zoom with the mouse wheel, including inside the truck. Releasing a camera drag never selects a part. Click a fitted part or an attachment marker to select its catalog category. Markers have priority over the meshes beneath them. The installed-parts list provides the same selection without using the 3D view. Switching trucks cancels the preceding assembly and any converter job it started.
3. Use the catalog to replace a part or add an instance from another truck. Duplicate creates an independent save unit. Use the attachment editor for lights, horns, and other hookups. Each attachment row has a remove button, including saved entries whose mount or mod definition is unavailable. Removal supports undo. Turn on **Advanced view** to see internal definition names, paths, and the instance-field editor, including wheel offsets and paint colors.
4. Undo and redo with the footer buttons or Ctrl+Z and Ctrl+Y. Text fields retain their normal text-editing shortcuts. History lasts for the running editing session.
5. Click **Save changes**. Load that save in ETS2 to inspect the result. If the game is running, load the edited save before saving again in game to avoid overwriting the edits.

Catalog cards render a larger 3D reference and rotate the model through a full turn while the pointer is over its preview. Static and rotating previews share their camera framing, with geometry centered on the rotation pivot to stay in view throughout the turn. Definitions without a mesh, such as engines, remain identifiable by name and category. Additional batches and search make the full catalog accessible. Internal paths and raw fields stay hidden until Advanced view is enabled.

Catalog thumbnails are cached locally in the browser, up to 512 images. Returning to a category or reopening the app reuses those images without importing geometry or rendering another thumbnail. Game/mod source changes and importer updates invalidate the cache. Only visible cards load; leaving the visible area cancels their queued requests, and hover requests take priority. Thumbnail generation shares one WebGL context, with at most two import jobs active. Hover rotation and the garage retain the full-detail models. First-time imports still need the local asset conversion.

The catalog hides equivalent definitions by default, including copies made for different truck brands. Appearance and functional fields must match; only price and unlock level are ignored. Within the current filters, the fitted definition or selected truck's brand is preferred. Check **Show duplicates** to display every matching definition. This preference is remembered locally, and all definitions remain available for loading saves.

The initial UI opens before importing game definitions. Choosing a save resolves its active mods, then imports its catalog and vehicle preview. An inline loading panel shows stages, elapsed time, and completed counts where available, including inside the first-visit guide. Catalog previews pause while the vehicle loads. The 3D viewer and preview renderer load on demand.

Selecting a marker highlights that marker in amber and clears the whole-part highlight. Selecting a fitted part restores its highlight and clears the marker selection. The marker's owner remains available in the attachment editor.

Truck edits update the existing scene. Unchanged meshes, textures, markers, and camera position are retained; only changed model instances are replaced. The server reuses loaded models and sends geometry only for models the current scene does not already have. Attachment transforms are recalculated so cab and chassis replacements correctly move dependent parts. Undo and redo use the same update path. A newly selected model still needs its first import.

Marker picking tests the visible ball and ring as well as a minimum screen-space click area. If several attachment points overlap, a chooser lists them so interior points can be selected independently. Imported textures retain their top-origin UV orientation in both the garage and catalog; thumbnail cache revisions regenerate older flipped previews.

The importer accepts ConverterPIX triangle rows with or without padding after their index, including rows numbered 10,000 and higher. Glass previews use a separate RGB texture because SCS glass texture alpha controls specular strength, not pane opacity; decal textures retain their alpha. The glass tint remains an approximation of the game's shader.

Saved hookups whose definition or attachment locator is unavailable are skipped during preview. Their saved entries remain intact, so an old missing mod does not prevent the rest of the truck from loading.

Flag cloth is defined separately from its pole mesh as a physics patch. S Garage builds a static two-triangle cloth preview from the local patch dimensions, anchor transform, and flag material, including shared definition files. Both garage and catalog use it. Wind simulation is not included, and no game assets are changed.

Toys with separate physics meshes (including Santa and bobblehead trucks) include those meshes at their configured attachment offsets in both previews. They are displayed at rest without physics animation.

ETS2 places accessory instances by definition category and named locators. The save does not provide a universal free-position transform for every part. S Garage therefore edits real save fields and hookups rather than offering arbitrary position controls that the game would ignore. Duplicated hookup entries can occupy the same locator.

## Saves and local data

Encrypted saves are decrypted in a temporary directory. Opening a save never decrypts the source file in place. A write preserves unrelated save units and creates a full backup of the save folder's files under:

`<selected save folder>/garage-backups/<UTC timestamp>/`

The app checks the source file's hash before writing, flushes a temporary file, checks the source again, and replaces `game.sii`. It refuses to write while ETS2 is running or after the source changes externally. The written file is plain-text SII. Restore a backup by copying its files back into the original save directory with ETS2 closed.

Settings, extracted definitions, converted models, and logs live in `%LOCALAPPDATA%/ETS2Garage`. Game archives remain in the installation. The project contains no game meshes, textures, saves, or DLC archives for redistribution. The definition cache is keyed by local source paths, file sizes, and modification times. Parsed models also include the importer version and selected look/variant in their cache key. First import and first previews can take time; converted data is reused afterward.

Saved mod dependencies select the local mod archives and Steam Workshop packages. If save metadata is absent, the profile's active-mod list is used. Universal Workshop packages and unambiguous single-package versions can be resolved automatically. Missing packages or ambiguous version choices produce preview issues while their original save units remain intact.

## Current limits

- Paint masks and accessory overrides, low/high light masks, and preview marker visibility are supported. Some specialized shaders, animated accessories, dynamic text plates, and other game-specific behavior need more rendering work. Geometry, materials, and attachment placement should be compared with ETS2 on representative trucks.
- A mixed-brand part may have no matching locator on its host. S Garage reports it and preserves its save instance. It cannot guarantee that all combinations are accepted or rendered identically by the game.
- Workshop packages with several version-specific alternatives require package-selection support. Locked or unsupported model formats report errors.
- Save selection initially uses the save directory's name. Steam Cloud synchronization remains Steam's responsibility.

## Development and verification

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python backend/server.py
```

In a second terminal:

```powershell
cd ui
npm ci
npm run dev
```

Vite proxies `/api` and `/cache` to the local Python server. `npm run build` creates the UI served by the desktop launcher. The backend uses Python's standard HTTP server and binds only to `127.0.0.1`.

The tests cover SII preservation, independent IDs, array counts, cross-brand swaps, undo/redo, backups, outside-write conflicts, running-game checks, quaternion transforms, wheel offsets, duplicated hookups, and HTTP request validation. Save-write tests use temporary fixtures.

Shared SII field/array helpers prevent different edit operations from serializing arrays differently. Quaternion composition is a separate helper because both accessory and hookup placement use it. The save session, asset store, and scene builder keep those responsibilities readable without adding a framework.

Catalog scene-building and disposal helpers are shared by static thumbnails and rotating previews so their material handling and resource cleanup stay consistent. A bounded queue limits concurrent preview imports.

## Tool sources

The bundled [ConverterPIX-SGarage fork](https://github.com/Senior-S/ConverterPIX-SGarage) adds definition bundles, binary viewer geometry, model batches, and a preview mode that skips unused collision and prefab exports. To rebuild it for development:

```powershell
# Clone beside this repository if it is not already present.
git clone https://github.com/Senior-S/ConverterPIX-SGarage.git ../ConverterPIX-SGarage
./scripts/build-converter-fork.ps1
./launch.ps1
```

The build helper selects the fork through `ETS_GARAGE_CONVERTER` for the current terminal. It defaults to the Visual Studio 2026 `v145` toolset; pass `-PlatformToolset v143` for Visual Studio 2022, or `-MSBuildPath` and `-ConverterSource` for custom locations. An already running garage needs to be stopped and reopened to use the terminal override. If Settings already specifies a converter, select the fork executable there, since that saved choice takes precedence over the terminal override. Settings persists the choice.

The backend checks the converter's capabilities once per executable revision. A supported fork uses one `definitions.sgbundle` for catalog import and lazy include reads, `.sgm` metadata plus `.sgb` arrays for new model exports, and one conversion batch for uncached fitted models and referenced hookups. Model jobs remain serial within the batch. Existing catalog JSON, complete PIM exports, and parsed model caches remain readable. An interrupted or failed batch retains incomplete markers and reports each failed model without discarding successful jobs.

Materials, looks, and variants still use the small PIT exports. Both geometry paths share the same material and attachment logic and the same viewer response format. Format readers live in `backend/converter_formats.py`; the fork's local `docs/GARAGE_MODES.md` and `docs/VIEWER_FORMAT.md` describe the file contracts.

Setup and release packaging pin the fork executable and its matching modified source archive to `cfdbd60d5654881bb8eb7997fe228e53dc1acbe7`.

- [ConverterPIX-SGarage](https://github.com/Senior-S/ConverterPIX-SGarage), pinned to `cfdbd60d5654881bb8eb7997fe228e53dc1acbe7`, converts PMG/PMD resources to native viewer geometry and PIM/PIT. Its LGPL license is in `tools/ConverterPIX-LICENSE.txt`.
- [SII Decrypt C++](https://github.com/liam-dong/SII-Decrypt-cpp), v1.0.0 source pinned to `7dd74d79cc0c847be602dc6bb8309f4ecacdbd2a`, decrypts and decodes temporary save copies. Setup verifies both the release ZIP and extracted executable checksums and upgrades the previously bundled Pascal 1.5.3 binary. Its MIT license is in `tools/SII-Decrypt-LICENSE.txt`.
- [SCS format documentation](https://modding.scssoft.com/wiki/Documentation/Engine/Formats) and [archive tools](https://modding.scssoft.com/wiki/Documentation/Tools/Game_Archive_Extractor) describe the game's asset formats.
