# Using S Garage

[Installation](INSTALLATION.md) · [Back to the project](../README.md)

## Choose a truck

TruckersMP assets are detected automatically when you open a save. S Garage reads the launcher's configured installation path, with fallback checks for the standard AppData and ProgramData locations. Installed ETS2 and shared packs supply models and textures for owned cars, buses, and TruckersMP accessories. ATS packs are excluded, and saved mods retain higher load priority. The first import prepares cached compatibility copies of TruckersMP archives; it does not modify the installation. Reopen the save after updating TruckersMP to refresh the imported assets.

On startup, the garage checks GitHub for a newer stable release without delaying editing. If the first attempt fails, it retries up to three times. An update notice links to the releases page; if GitHub cannot be reached, the notice says a newer version may be available. You can dismiss either notice. Updates are downloaded manually.

Select **Profile**, **Save file**, then an owned **Truck**. Switching trucks cancels the previous model load. Opening a save reads a temporary decrypted copy; the original changes only when you click **Save changes**.

## Explore

Drag to orbit and scroll to zoom, including inside the cab. Click a fitted part or marker to choose its category; the installed-parts list works too. Overlapping markers show a chooser so you can select the intended point.

| Preview control | Options |
| --- | --- |
| Lighting | **Day** by default; **Afternoon** uses warmer, lower sunlight; **Night** dims the surroundings so truck lights are easier to inspect. |
| Lights | **Off** by default; **Low** for low beams and position lights; **High** adds high beams and auxiliary lights. |
| Markers | **All** by default; **Selected only** keeps the selected marker visible; **Hidden** clears the view. |

Headlight previews use the installed definition's beam masks, colors, reflector positions, angles, and ranges. Lamp emission stays on the actual lens geometry. Auxiliary beam illumination is grouped at the front and roof to keep large lightbars responsive. Brightness and reflections remain approximate browser renderings; brake lights, indicators, and reversing lights stay off in this parked preview.

These controls do not change your save.

## Choose accessories

Selecting a part or marker switches the catalog category. Search and filter by make to find parts. Choosing another marker in the same category keeps your search.

Hover over a catalog preview to rotate it. Equivalent definitions are hidden initially; enable **Show duplicates** to display them all. Some definitions, such as engines, have no visible mesh.

![Accessory selection and catalog](media/accessories.png)

**Replace** changes the selected part or hookup. **Add** fits an accessory or fills an empty marker. Filling a marker switches it to Replace. **Copy / Duplicate** creates an independent instance; it may overlap the original because ETS2 controls attachment placement.

Mixed-brand parts can lack a compatible locator or behave differently in game. Always inspect the final result in ETS2.

## Paint your truck

Click **Paint** above the 3D view, or select the installed paint job. The catalog shows paint jobs from your installed game, DLC, and mods for the current truck and cab. Designs with artwork show that artwork on your selected cab, using the paint's default colors. Hover over a preview to rotate it and see both sides. Plain-color paints keep their color swatches.

Only visible previews load, and thumbnails are cached locally. Switching categories cancels unfinished previews. Browsing or hovering over a paint does not change your truck or its edit history.

Local paint-only mods are discovered when you open a save, even if that save has not used them yet. The garage reads `.scs` and `.zip` packages and extracted folders in your ETS2 `mod` directory. It also recognizes paint files extracted directly into that directory. Other mods follow the save's active mod list and load order. Enable the paint mod in ETS2 before using its paint job in game.

Choose a paint job to apply it to the truck preview. In **Paint colors** on the left, change the base, design, metallic-flake, or flip colors supported by that paint job, then click **Apply colors**. Colors marked **Locked** cannot be edited for that design. Each application is one undoable change; your save is written only when you click **Save changes**.

The preview approximates the game's paint shaders, including metallic finishes. Inspect the result in ETS2 after saving.

Switching paint jobs carries your whole palette if you customized any color. If the current paint still has its default palette, the new paint uses its own defaults. Locked colors always follow the new design. **Reset colors**, beside **Apply colors**, restores the selected paint's original palette immediately; you can undo that reset.

## Undo and advanced controls

Use the bottom **Undo / Redo** buttons or **Ctrl+Z / Ctrl+Y**. Text inputs keep normal editing shortcuts. Undoing an added hookup clears its marker and returns it to Add mode.

Click **History** to see changes across all trucks in the loaded save. Click an applied change to undo it and all later changes at once, or **Opened save** to undo everything. Dimmed changes can be restored with their **Redo** action. Making a new edit after undoing discards the redo branch.

History lasts for the running server session. Stopping the app clears history and unsaved edits. Browser tabs share one session; reload a stale tab before editing.

**Advanced view** reveals internal names, paths, and supported instance fields such as paint colors and wheel offsets. Arbitrary positioning is not available for every accessory because ETS2 does not support a universal accessory transform in saves.

## Save

Click **Save changes**, then load the edited save in ETS2. A backup is created before writing. You can save with ETS2 open, but load the edited save before saving again in game to avoid overwriting your changes. Keep an experimental manual save while trying unusual combinations.

To reverse a saved change after ending the session, **[restore a backup](INSTALLATION.md#restore-a-save-backup)**.


## Custom trailers

Opening a save still selects the assigned truck. Open the vehicle dropdown below **Installed parts** to browse **Trucks** first, then expand **Trailers**. Only trailers owned by the profile appear. Doubles and other linked combinations appear as one trailer, with all sections together in the preview. Each section has its own edit points, and installed parts show their section number. Select a part or edit point to change that section, including its paint. Editing parts preserves the saved trailer chain. Models without coupling locators use approximate preview spacing and show a preview issue.

Trailers use the same part picker, 3D attachment markers, add/replace/copy controls, paint editor, advanced fields, undo/redo, history, and save backups. Trailer bodies mount on the chassis, and wheel parts retain their axle offsets. You can mix accessories across vehicles when their categories match. Compatibility and the final appearance still depend on ETS2 and the installed definitions.

Save changes writes edits across all trucks and trailer sections in the session. The next time you open the save, the assigned truck is selected again. The expanded catalog requires a fresh asset import on the first launch of this version.
