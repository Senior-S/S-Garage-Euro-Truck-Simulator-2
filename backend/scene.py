"""Assemble save instances at the attachment locators exported from game models."""
from __future__ import annotations

import math
import re
import hashlib
import json
from concurrent.futures import CancelledError
from assets import _numbers


IDENTITY = {"position": [0, 0, 0], "rotation": [0, 0, 0, 1], "scale": [1, 1, 1]}


def multiply(a: list, b: list) -> list:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return [aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz]


def compose(parent: dict, local: dict) -> dict:
    """Compose a locator with its owner, using the API's XYZW quaternion order."""
    rotation = parent.get("rotation") or IDENTITY["rotation"]
    scale = parent.get("scale") or IDENTITY["scale"]
    position = [v * s for v, s in zip(local.get("position") or IDENTITY["position"], scale)]
    rotated = multiply(multiply(rotation, [*position, 0]), [-rotation[0], -rotation[1], -rotation[2], rotation[3]])[:3]
    return {"position": [v + p for v, p in zip(rotated, parent.get("position") or IDENTITY["position"])],
            "rotation": multiply(rotation, local.get("rotation") or IDENTITY["rotation"]),
            "scale": [a * b for a, b in zip(scale, local.get("scale") or IDENTITY["scale"])]}


def build_scene(truck: dict, assets, cancelled=None, model_cache=None) -> dict:
    def check_cancelled():
        if cancelled and cancelled():
            raise CancelledError()

    check_cancelled()
    parts, points, issues = [], [], []
    accessories = truck["accessories"]
    catalog = assets.catalog()
    check_cancelled()
    by_path = {entry["path"]: entry for entry in catalog}
    by_hook = {entry["unitId"]: entry for entry in catalog if entry.get("category") == "hookup"}
    categories = tuple(dict.fromkeys(entry["category"] for entry in catalog))
    category_set = set(categories)
    installed = {}
    for accessory in accessories:
        check_cancelled()
        installed.setdefault(accessory["category"], []).append(accessory)
    mounts = []
    pending = []
    models = model_cache if model_cache is not None else {}
    used_models = set()
    active_paint = next((a for a in accessories if a["category"] == "paint_job"), None)
    paint_color = active_paint["fields"].get("base_color") if active_paint else None
    paint_job = assets.paint_job(active_paint["dataPath"], cancelled=cancelled) if active_paint and hasattr(assets, "paint_job") else {}
    paint_fields = {**paint_job.get("fields", {}), **(active_paint["fields"] if active_paint else {})}

    # A model conversion is shared by all save instances of the same definition.
    def model_for(entry, accessory=None):
        check_cancelled()
        fields = accessory.get("fields", {}) if accessory else {}
        look, variant = fields.get("look"), fields.get("variant")
        key = entry["path"], look, variant
        used_models.add(key)
        if key not in models:
            if cancelled:
                models[key] = assets.model(entry["path"], look, variant, cancelled=cancelled)
            elif look or variant:
                models[key] = assets.model(entry["path"], look, variant)
            else:
                models[key] = assets.model(entry["path"])
            models[key] = {**models[key], "key": hashlib.sha256(json.dumps(key).encode()).hexdigest()}
        return models[key]

    def place(accessory, model, transform, hookup=None):
        definition = by_path.get(accessory["dataPath"], {})
        instance_color = paint_color or accessory["fields"].get("paint_color")
        unit = definition.get("unitId", "").split(".")[0]
        override = paint_job.get("overrides", {}).get(f'{accessory["category"]}.{unit}')
        paint_texture = override or paint_job.get("texture")
        if paint_texture:
            instance_color = paint_fields.get("base_color")
        color = _numbers(instance_color)[:3] if instance_color else None
        paint = None
        # Material metadata identifies paint shaders. Geometry is reused unchanged.
        if color and any(piece["material"].get("paintable") for piece in model["pieces"]):
            paint = {"color": color}
            if paint_texture:
                paint.update({"paintTexture": paint_texture, "paintColors": [paint_fields.get(name, fallback) for name, fallback in (("mask_r_color", "(1,0,0)"), ("mask_g_color", "(0,1,0)"), ("mask_b_color", "(0,0,1)"))], "airbrush": paint_fields.get("airbrush") == "true", "paintUv": 1})
                paint["paintColors"] = [_numbers(value)[:3] for value in paint["paintColors"]]
            if paint_fields.get("flipflake") == "true":
                paint.update({"metalness": .75, "roughness": .25, "flipColor": _numbers(paint_fields.get("flip_color", "(0,0,0)"))[:3], "flakeColor": _numbers(paint_fields.get("flake_color", "(1,1,1)"))[:3], "flipStrength": float(paint_fields.get("flip_strength", "1"))})
        parts.append({"id": accessory["id"], "definition": accessory["dataPath"], "category": accessory["category"],
                      "model": model, "paint": paint, "hookup": hookup, **transform})
        for diagnostic in model.get("diagnostics", []):
            message = f'{accessory["category"]}: {diagnostic}'
            if message not in issues:
                issues.append(message)
        for locator in model.get("locators", []):
            check_cancelled()
            name = locator["name"]
            world = compose(transform, locator)
            slot = name.startswith("slot_") or any(s["name"] == name for s in accessory.get("slots", []))
            builtin = locator.get("hookup")
            if slot:
                points.append({"name": name, "kind": "hookup", "accessoryId": accessory["id"],
                               "hookup": next((s["hookup"] for s in accessory.get("slots", []) if s["name"] == name), None), **world})
            elif not builtin and not name.startswith(("shadow", "cam_", "hook_", "wp")):
                mounts.append({"name": name, "owner": accessory["id"], "ownerCategory": accessory["category"], **world})
        # Render user-installed hookups, including multiple entries on one locator.
        for attachment in accessory.get("slots", []):
            check_cancelled()
            entry = by_hook.get(attachment["hookup"])
            locations = [loc for loc in model.get("locators", []) if loc["name"] == attachment["name"]]
            if not locations or not entry:
                continue
            if not entry.get("model"):
                continue
            try:
                hook_model = model_for(entry)
            except (ValueError, FileNotFoundError, RuntimeError) as error:
                issues.append(str(error))
                continue
            for locator in locations:
                parts.append({"id": accessory["id"], "definition": entry["path"], "category": "hookup", "hookup": attachment["hookup"],
                              "model": hook_model, **compose(transform, locator)})

    # Cab and frame models use the truck's coordinate system. Attachments use local origins.
    for accessory in sorted(accessories, key=lambda a: a["category"] not in ("chassis", "cabin")):
        check_cancelled()
        entry = by_path.get(accessory["dataPath"])
        if not entry:
            issues.append(f'Definition unavailable: {accessory["dataPath"]}. Enable its local DLC/mod source to preview it.')
            continue
        if not entry.get("model"):
            continue
        try:
            model = model_for(entry, accessory)
        except (ValueError, FileNotFoundError, RuntimeError) as error:
            issues.append(str(error))
            continue
        if accessory["category"] in ("cabin", "chassis"):
            place(accessory, model, IDENTITY)
        else:
            pending.append((accessory, model))
    # Resolve by name, in passes, so accessory-provided locators can host other parts.
    while pending:
        check_cancelled()
        remaining = []
        for accessory, model in pending:
            check_cancelled()
            category = accessory["category"]
            if accessory["type"] == "vehicle_wheel_accessory":
                front = category.startswith("f_")
                offset = int(accessory["fields"].get("offset", "0"))
                prefix = "wheel_f_" if front else "wheel_r_"
                targets = [m for m in mounts if any(re.fullmatch(prefix + str(side) + r"(?:_\d+)?", m["name"]) for side in (offset, offset + 1))]
                for mount in targets:
                    # Wheel components are modeled for the outer face on the right side.
                    transform = {**mount, "scale": list(mount["scale"])}
                    if mount["position"][0] < 0:
                        transform["scale"][0] *= -1
                    place(accessory, model, {key: transform[key] for key in IDENTITY})
            else:
                if category == "interior":
                    targets = [m for m in mounts if m["name"] == "ext_interior"]
                else:
                    mount_name = "swheel" if category == "steering_w" else category
                    targets = [m for m in mounts if m["name"] == mount_name]
                    if not targets:
                        targets = [m for m in mounts if m["name"].startswith(category + "_")]
                # Donor mounts on the cab/frame win over mounts introduced by other accessories.
                primary = [m for m in targets if m["ownerCategory"] in ("cabin", "chassis")]
                targets = primary or targets
                for target in list(targets):
                    place(accessory, model, {key: target[key] for key in IDENTITY})
            if not targets:
                remaining.append((accessory, model))
        if len(remaining) == len(pending):
            break
        pending = remaining
    for accessory, model in pending:
        check_cancelled()
        issues.append(f'{accessory["category"]}: no matching attachment locator. This instance remains in the save but is omitted from the preview.')
    for mount in mounts:
        name = mount["name"]
        mount_category = "steering_w" if name == "swheel" else name
        exact = installed.get(mount_category, [])
        if not exact:
            exact = next((items for category, items in installed.items() if name.startswith(category + "_")), [])
        available_category = mount_category if mount_category in category_set else next((category for category in categories if name.startswith(category + "_")), None)
        if not available_category:
            continue
        for item in exact or [None]:
            points.append({"name": name, "kind": "part", "category": available_category,
                           "accessoryId": item["id"] if item else None, **{key: mount[key] for key in IDENTITY}})
    check_cancelled()
    for key in list(models):
        if key not in used_models:
            del models[key]
    return {"parts": parts, "points": points, "issues": list(dict.fromkeys(issues)),
            "truckId": truck["id"], "materialFidelity": "Game geometry and locators; approximate browser materials."}
