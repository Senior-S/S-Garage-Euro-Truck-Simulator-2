# Using S Garage

[Installation](INSTALLATION.md) · [Back to the project](../README.md)

## Choose a truck

Select **Profile**, **Save file**, then an owned **Truck**. Switching trucks cancels the previous model load. Opening a save reads a temporary decrypted copy; the original changes only when you click **Save changes**.

## Explore

Drag to orbit and scroll to zoom, including inside the cab. Click a fitted part or marker to choose its category; the installed-parts list works too. Overlapping markers show a chooser so you can select the intended point.

| Preview control | Options |
| --- | --- |
| Lights | **Off** by default; **Low** for low beams and position lights; **High** adds high beams and auxiliary lights. |
| Markers | **All** by default; **Selected only** keeps the selected marker visible; **Hidden** clears the view. |

These controls do not change your save.

## Choose accessories

Selecting a part or marker switches the catalog category. Search and filter by make to find parts. Choosing another marker in the same category keeps your search.

Hover over a catalog preview to rotate it. Equivalent definitions are hidden initially; enable **Show duplicates** to display them all. Some definitions, such as engines, have no visible mesh.

![Accessory selection and catalog](media/accessories.png)

**Replace** changes the selected part or hookup. **Add** fits an accessory or fills an empty marker. Filling a marker switches it to Replace. **Copy / Duplicate** creates an independent instance; it may overlap the original because ETS2 controls attachment placement.

Mixed-brand parts can lack a compatible locator or behave differently in game. Always inspect the final result in ETS2.

## Undo and advanced controls

Use the bottom **Undo / Redo** buttons or **Ctrl+Z / Ctrl+Y**. Text inputs keep normal editing shortcuts. Undoing an added hookup clears its marker and returns it to Add mode.

History lasts for the running server session. Stopping the app clears history and unsaved edits. Browser tabs share one session; reload a stale tab before editing.

**Advanced view** reveals internal names, paths, and supported instance fields such as paint colors and wheel offsets. Arbitrary positioning is not available for every accessory because ETS2 does not support a universal accessory transform in saves.

## Save

Close ETS2, click **Save changes**, then start ETS2 and load the edited save. A backup is created before writing. Keep an experimental manual save while trying unusual combinations.

To reverse a saved change after ending the session, **[restore a backup](INSTALLATION.md#restore-a-save-backup)**.
