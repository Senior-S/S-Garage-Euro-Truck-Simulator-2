# S Garage · Euro Truck Simulator 2

[![Total downloads](https://img.shields.io/github/downloads/Senior-S/S-Garage-Euro-Truck-Simulator-2/total?label=Downloads&color=blue)](https://github.com/Senior-S/S-Garage-Euro-Truck-Simulator-2/releases)

**A free local 3D truck editor and save editor for ETS2.** Build your truck visually: mix accessories from different trucks, duplicate parts, explore attachment points, and preview changes before loading your save in the game.

**[Download for Windows](https://github.com/Senior-S/S-Garage-Euro-Truck-Simulator-2/releases)** · **[Installation guide](docs/INSTALLATION.md)** · **[User guide](docs/USER_GUIDE.md)** · **[Get help](https://github.com/Senior-S/S-Garage-Euro-Truck-Simulator-2/issues/new/choose)**

> [!WARNING]
> **S Garage is a work in progress (WIP), not a finished tool.** Expect bugs, missing features, and differences between the preview and ETS2. Edits may produce a save that does not load correctly in game. Experiment with a separate manual save and keep a backup of your original saves.

### Known missing features and limitations

- **v0.3.0 adds owned trailer editing and faster asset imports with ConverterPIX-SGarage.** This remains a prerelease; keep backups and inspect edited trucks in ETS2.
- Painting uses truck paint jobs and their supported color channels. Independent recoloring of arbitrary parts is not available, and metallic finishes only approximate the game's shaders.
- Some parts, materials, lighting, and mod assets may render incorrectly or be missing from the preview.
- Some accessory combinations may not work correctly in ETS2, even if they appear in the garage.

This list is not exhaustive. Please [report bugs or missing features](https://github.com/Senior-S/S-Garage-Euro-Truck-Simulator-2/issues/new/choose), or add **`seniors` on Discord**.

![S Garage showing a customized Scania in its 3D garage](docs/media/overview.png)

## See it before downloading

![A short demonstration of the garage, light modes, and attachment markers](docs/media/garage-demo.gif)

[Watch or download the full demo video](https://github.com/Senior-S/S-Garage-Euro-Truck-Simulator-2/releases/download/v0.1.0/S-Garage-demo.mp4).

These are real captures of the app using locally installed game assets. The preview approximates ETS2's rendering; lighting, materials, and some accessories can still look different in game. This is an **early preview release**.

## What you can do

- Open a profile and save, then choose an owned truck or trailer, including trailer chain sections.
- Inspect the truck in 3D, including its interior, and select parts or attachment markers.
- Replace accessories, mix parts across trucks, and duplicate parts or hookups.
- Browse visual catalog previews that rotate on hover; duplicates stay hidden unless enabled.
- Undo and redo edits before saving.
- Open History to undo or redo several edits at once, and choose game paint jobs with editable colors. Artwork paints show rotating cab previews; customized palettes carry across paint changes, and Reset colors restores a design's defaults.
- Preview lights in **Off**, **Low**, or **High** mode, including roof and auxiliary lights.
- Show **All** markers, the **Selected only** marker, or hide them completely.
- Enable **Advanced view** for internal names and supported save-field editing.

![Attachment selection and the visual accessory catalog](docs/media/accessories.png)

## Download and start

You need **Windows 10/11, 64-bit**, an installed copy of **Euro Truck Simulator 2**, and a browser with WebGL support. S Garage uses your installed game, DLC, and available mods. Game assets and saves are not included in the download.

1. Open the **[Downloads page](https://github.com/Senior-S/S-Garage-Euro-Truck-Simulator-2/releases)**. A GitHub account is not required.
2. Under **Assets**, download **`S-Garage-v0.3.0-Windows-x64.zip`**. Choose this file instead of GitHub's automatically generated “Source code” downloads.
3. Right-click the ZIP and select **Extract All**. Keep the extracted files together.
4. Open the extracted **S Garage** folder and double-click **`S Garage.exe`**.
5. Your browser opens the garage. Keep the small S Garage window open while editing; use **Stop garage** when finished.

**No Python, Node.js, Git, or installation wizard is needed for the portable download.** Game and profile folders are detected automatically; open **Settings** to select them yourself if necessary. First-time imports can take a while; later visits reuse local caches.

See the **[installation guide](docs/INSTALLATION.md)** for updating and troubleshooting.

## Your first truck edit

1. In ETS2, make a separate manual save for experimenting, then open that save in S Garage.
2. Choose your **Profile**, **Save file**, and **Truck**.
3. Click a part or marker, then choose an accessory from the catalog. Use **Undo** if you change your mind.
4. Click **Save changes**. The app creates a backup before writing the selected save. If ETS2 is running, load the edited save before saving again in game; otherwise the game may overwrite your edits.
5. Load the edited save in ETS2 to inspect the result.

Closing the browser keeps the local server running. Stopping S Garage ends the editing session; save your edits first. Light and marker controls only affect the preview.

More detail: **[User guide](docs/USER_GUIDE.md)** · **[Restore a save backup](docs/INSTALLATION.md#restore-a-save-backup)**.

## What to expect

Some unusual combinations have no compatible attachment point or behave differently in ETS2. Missing old mod accessories are skipped in the preview, while their saved entries remain intact. Flags and physics toys appear at rest. Workshop mods with ambiguous version packages and some specialized shaders need further support.

S Garage runs locally at `http://127.0.0.1:8765`. Your saves and imported game assets stay on your computer. Settings and caches are stored in `%LOCALAPPDATA%\ETS2Garage`.

## Help, contact, and support

**[Report a problem](https://github.com/Senior-S/S-Garage-Euro-Truck-Simulator-2/issues/new/choose)**, or add **`seniors` on Discord**. Include your S Garage version, ETS2 version, what you clicked, and a screenshot or error message. Remove personal paths and usernames from logs before sharing them.

S Garage is free. Voluntary support is welcome; contact **`seniors` on Discord** for donation details. Donations are not required to download or use the app.

## License and credits

The original code is **source-available under [PolyForm Noncommercial 1.0.0](LICENSE)**. Noncommercial use, modification, and sharing are permitted under its terms; commercial redistribution requires separate permission. Third-party components retain their own licenses—see **[third-party notices](THIRD_PARTY.md)**.

Euro Truck Simulator 2 and its game assets belong to **SCS Software**. S Garage is an unofficial community tool, unaffiliated with SCS Software.

For developers: **[Build and contribute](CONTRIBUTING.md)** · **[Technical documentation](docs/DEVELOPMENT.md)**.
