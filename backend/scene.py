"""Assemble save instances at the attachment locators exported from game models."""
from __future__ import annotations

import math
import re
import hashlib
import json
from concurrent.futures import CancelledError
from assets import _numbers, accessory_options


IDENTITY = {"position": [0, 0, 0], "rotation": [0, 0, 0, 1], "scale": [1, 1, 1]}
MOUNT_CATEGORIES = {"swheel": "steering_w", "doorsteps": "doorstep"}


def paint_material(color: list, fields: dict, paint_texture: str | None = None) -> dict:
    """Use the same paint shader settings for installed parts and catalog previews."""
    paint = {"color": color}
    if paint_texture:
        paint.update({"paintTexture": paint_texture, "paintColors": [fields.get(name, fallback) for name, fallback in (("mask_r_color", "(1,0,0)"), ("mask_g_color", "(0,1,0)"), ("mask_b_color", "(0,0,1)"))], "airbrush": fields.get("airbrush") == "true", "paintUv": 1})
        paint["paintColors"] = [_numbers(value)[:3] for value in paint["paintColors"]]
    if fields.get("flipflake") == "true":
        paint.update({"metalness": .18, "roughness": .42, "flipColor": _numbers(fields.get("flip_color", "(0,0,0)"))[:3], "flakeColor": _numbers(fields.get("flake_color", "(1,1,1)"))[:3], "flipStrength": float(fields.get("flip_strength", "1"))})
    return paint


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


def build_scene(truck: dict, assets, cancelled=None, model_cache=None, *, prune_models=True) -> dict:
    def check_cancelled():
        if cancelled and cancelled():
            raise CancelledError()

    check_cancelled()
    parts, points, issues = [], [], []
    models = model_cache if model_cache is not None else {}
    sections = truck.get("sections", [])
    if len(sections) > 1:
        rear_hook = None
        previous_scene, previous_transform = None, IDENTITY
        for index, section in enumerate(sections):
            check_cancelled()
            scene = build_scene(section, assets, cancelled, models, prune_models=False)
            hooks = {}
            for part in scene["parts"]:
                check_cancelled()
                if part["category"] == "chassis":
                    for locator in part["model"].get("locators", []):
                        if locator["name"] in ("hook", "s_hook"):
                            hooks.setdefault(locator["name"], compose(part, locator)["position"])
            transform = IDENTITY
            if index:
                if rear_hook is not None and "hook" in hooks:
                    # Show a straight chain with the game's coupling points coincident.
                    offset = [parent - child for parent, child in zip(rear_hook, hooks["hook"])]
                else:
                    # Only scan geometry when a model lacks a coupling locator.
                    bounds = [[], []]
                    for side, (local_scene, parent) in enumerate(((previous_scene, previous_transform), (scene, IDENTITY))):
                        for part in local_scene["parts"]:
                            check_cancelled()
                            world = compose(parent, part)
                            for piece in part["model"].get("pieces", []):
                                positions = piece.get("positions", [])
                                if not positions:
                                    continue
                                axes = [(min(positions[axis::3]), max(positions[axis::3])) for axis in range(3)]
                                bounds[side].extend(compose(world, {**IDENTITY, "position": [x, y, z]})["position"][2]
                                                    for x in axes[0] for y in axes[1] for z in axes[2])
                    offset = [0, 0, max(bounds[0], default=previous_transform["position"][2]) - min(bounds[1], default=0) + .5]
                    issues.append(f'Section {section.get("section", index + 1)}: coupling locators unavailable; preview spacing is approximate.')
                transform = {**IDENTITY, "position": offset}
            parts.extend({**part, **compose(transform, part)} for part in scene["parts"])
            points.extend({**point, **compose(transform, point)} for point in scene["points"])
            issues.extend(f'Section {section.get("section", index + 1)}: {issue}' for issue in scene["issues"])
            rear_hook = compose(transform, {**IDENTITY, "position": hooks["s_hook"]})["position"] if "s_hook" in hooks else None
            previous_scene, previous_transform = scene, transform
        if prune_models:
            used = {part["model"]["key"] for part in parts}
            for key in list(models):
                if models[key]["key"] not in used:
                    del models[key]
        return {"parts": parts, "points": points, "issues": list(dict.fromkeys(issues)),
                "truckId": truck["id"], "materialFidelity": "Game geometry and locators; approximate browser materials."}
    progress = getattr(assets, "progress", None)
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
    used_models = set()
    active_paint = next((a for a in accessories if a["category"] == "paint_job"), None)
    paint_color = active_paint["fields"].get("base_color") if active_paint else None
    if progress:
        progress("Preparing paint", "Reusing cached masks or importing the selected paint job.")
    paint_keys = {f'{accessory["category"]}.{by_path.get(accessory["dataPath"], {}).get("unitId", "").split(".")[0]}' for accessory in accessories}
    paint_job = assets.paint_job(active_paint["dataPath"], cancelled=cancelled, accessory_keys=paint_keys) if active_paint and hasattr(assets, "paint_job") else {}
    issues.extend(paint_job.get("diagnostics", []))
    paint_fields = {**paint_job.get("fields", {}), **(active_paint["fields"] if active_paint else {})}
    if hasattr(assets, "prepare_models"):
        requests = set()
        for accessory in accessories:
            entry = by_path.get(accessory["dataPath"])
            fields = accessory.get("fields", {})
            key = accessory["dataPath"], fields.get("look"), fields.get("variant")
            if entry and entry.get("model") and key not in models:
                requests.add(key)
            for attachment in accessory.get("slots", []):
                hook = by_hook.get(attachment["hookup"])
                if hook and hook.get("model") and (hook["path"], None, None) not in models:
                    requests.add((hook["path"], None, None))
        if requests:
            assets.prepare_models(sorted(requests, key=lambda request: tuple(value or "" for value in request)), cancelled=cancelled)
        check_cancelled()

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
        options = accessory_options(definition)
        if options["paintColor"]:
            instance_color = accessory["fields"].get("paint_color") or options["defaultColor"]
            paint_texture = None
        color = _numbers(instance_color)[:3] if instance_color else None
        paint = None
        # Material metadata identifies paint shaders. Geometry is reused unchanged.
        if color and any(piece["material"].get("paintable") for piece in model["pieces"]):
            paint = paint_material(color, {} if options["paintColor"] else paint_fields, paint_texture)
            accessory_color = accessory["fields"].get("paint_color")
            if accessory_color:
                paint["accessoryColor"] = _numbers(accessory_color)[:3]
        text_texture = None
        if any(piece["material"].get("driverPlate") for piece in model["pieces"]):
            text = accessory["fields"].get("text", '""')
            try:
                text = json.loads(text)
            except (ValueError, TypeError):
                pass
            try:
                text_texture = assets.driver_plate_texture(str(text), cancelled)
            except (OSError, RuntimeError, ValueError, AttributeError, IndexError) as error:
                issues.append(f'{accessory["category"]}: plate text preview unavailable: {error}')
        parts.append({"id": accessory["id"], "definition": accessory["dataPath"], "category": accessory["category"],
                      "model": model, "paint": paint, "textTexture": text_texture, "hookup": hookup, **transform})
        for diagnostic in model.get("diagnostics", []):
            message = f'{accessory["category"]}: {diagnostic}'
            if message not in issues:
                issues.append(message)
        if accessory["category"] == "interior":
            bones = model.get("steeringBones", [])
            steering = next((bone for bone in bones if bone["name"] == "steering_w"), None)
            if steering:
                chain = []
                while steering:
                    chain.append(steering)
                    steering = bones[steering["parent"]] if steering["parent"] != 255 else None
                world = transform
                for bone in reversed(chain):
                    world = compose(world, {"position": bone["translation"], "rotation": bone["rotation"], "scale": bone["scale"]})
                # Accessory meshes use X across the wheel; the steering bone
                # uses Z. Align the spokes without changing the tilt.
                world = compose(world, {**IDENTITY, "rotation": [0, -math.sqrt(.5), 0, math.sqrt(.5)]})
                mounts.append({"name": "swheel", "owner": accessory["id"], "ownerCategory": "interior", **world})
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
    for index, accessory in enumerate(sorted(accessories, key=lambda a: a["category"] not in ("chassis", "cabin"))):
        check_cancelled()
        entry = by_path.get(accessory["dataPath"])
        if progress:
            progress("Loading fitted parts", (entry or {}).get("name", accessory["category"].replace("_", " ")), index, len(accessories))
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
    if progress:
        progress("Placing parts and attachments", "Matching parts to their mounting points.", len(accessories), len(accessories))
    while pending:
        check_cancelled()
        remaining = []
        # Interior skeleton mounts must exist before fitting the steering wheel.
        for accessory, model in sorted(pending, key=lambda item: item[0]["category"] != "interior"):
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
                    targets = [m for m in mounts if MOUNT_CATEGORIES.get(m["name"], m["name"]) == category]
                    if not targets:
                        targets = [m for m in mounts if m["name"].startswith(category + "_")]
                # Donor mounts on the cab/frame win over mounts introduced by other accessories.
                primary = [m for m in targets if m["ownerCategory"] in ("cabin", "chassis")]
                if category == "steering_w":
                    primary = [m for m in targets if m["ownerCategory"] == "interior"] or primary
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
        mount_category = MOUNT_CATEGORIES.get(name, name)
        if mount_category == "steering_w" and mount["ownerCategory"] != "interior" and any(m["name"] == "swheel" and m["ownerCategory"] == "interior" for m in mounts):
            continue
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
    headlight = next(iter(installed.get("head_light", [])), None)
    if headlight and hasattr(assets, "head_lights"):
        try:
            chassis = next((part for part in parts if part["category"] == "chassis"), IDENTITY)
            auxiliary = {}
            rotation = chassis.get("rotation", IDENTITY["rotation"])
            inverse = [-rotation[0], -rotation[1], -rotation[2], rotation[3]]
            for part in parts:
                for locator in part["model"].get("locators", []):
                    if not (locator.get("hookup") or "").startswith("flare.vehicle.aux_light"):
                        continue
                    world = compose(part, locator)
                    delta = [p - origin for p, origin in zip(world["position"], chassis.get("position", IDENTITY["position"]))]
                    local = multiply(multiply(inverse, [*delta, 0]), rotation)[:3]
                    mode = "roof_beam" if local[1] > 2 else "front_beam"
                    auxiliary.setdefault(mode, []).append(local)
            lighting = assets.head_lights(headlight["dataPath"], cancelled=cancelled, auxiliary=bool(auxiliary))
            issues.extend(lighting.get("diagnostics", []))
            lighting["auxiliary"] = [{"mode": mode, "position": [sum(point[axis] for point in positions) / len(positions) for axis in range(3)]}
                                     for mode, positions in auxiliary.items()]
            key = hashlib.sha256(json.dumps(lighting, sort_keys=True).encode()).hexdigest()
            parts.append({"id": headlight["id"], "category": "head_light", "definition": headlight["dataPath"],
                          "modelKey": key, "model": {"key": key, "pieces": [], "locators": [], "headLights": lighting},
                          **{name: chassis.get(name, default) for name, default in IDENTITY.items()}})
        except (RuntimeError, FileNotFoundError) as error:
            issues.append(f"Headlight projection unavailable: {error}")
    if progress:
        progress("Sending vehicle preview", f"{len(parts)} visible part instances.")
    for item in parts + points:
        item.update(vehicleId=truck["id"], section=truck.get("section", 1))
    if prune_models:
        for key in list(models):
            if key not in used_models:
                del models[key]
    return {"parts": parts, "points": points, "issues": list(dict.fromkeys(issues)),
            "truckId": truck["id"], "materialFidelity": "Game geometry and locators; approximate browser materials."}
