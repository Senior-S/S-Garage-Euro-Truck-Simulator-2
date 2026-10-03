"""Lossless SII save edits. Only the chosen vehicle and its accessories change."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone


UNIT = re.compile(r"^(\w+)\s*:\s*([\w.]+)\s*\{\r?\n.*?^\}", re.M | re.S)
FIELD = re.compile(r"^[ \t]+([\w]+(?:\[\d+\])?):[ \t]*(.*?)\r?$", re.M)


def fields(block: str) -> dict[str, str]:
    return dict(FIELD.findall(block))


def refs(block: str, name: str) -> list[str]:
    values = fields(block)
    count = int(values.get(name, "0"))
    indices = {int(key[len(name) + 1:-1]) for key in values if re.fullmatch(re.escape(name) + r"\[\d+\]", key)}
    if indices != set(range(count)):
        raise ValueError(f"Invalid {name} array: count and entries differ.")
    return [values[f"{name}[{i}]"] for i in range(count)]


def unquote(value: str) -> str:
    return json.loads(value) if value.startswith('"') else value


def category(path: str) -> str:
    parts = path.strip("/").split("/")
    if len(parts) > 4 and parts[:3] == ["def", "vehicle", "truck"]:
        return parts[5] if parts[4] == "accessory" and len(parts) > 5 else "truck" if parts[4] == "data.sii" else parts[4]
    if len(parts) > 2 and parts[:2] == ["def", "vehicle"]:
        return parts[2]
    return "unknown"


def set_field(block: str, key: str, value: str) -> str:
    newline = "\r\n" if "\r\n" in block else "\n"
    pattern = re.compile(r"(^[ \t]+" + re.escape(key) + r":[ \t]*)[^\r\n]*", re.M)
    if pattern.search(block):
        return pattern.sub(lambda m: m[1] + value, block, count=1)
    return block[:-1] + f" {key}: {value}{newline}" + "}"


def set_array(block: str, key: str, values: list[str]) -> str:
    newline = "\r\n" if "\r\n" in block else "\n"
    block = re.sub(r"^[ \t]+" + re.escape(key) + r"\[\d+\]:[^\r\n]*\r?\n", "", block, flags=re.M)
    block = set_field(block, key, str(len(values)))
    pattern = re.compile(r"(^[ \t]+" + re.escape(key) + r": \d+)(\r?\n)", re.M)
    return pattern.sub(lambda m: m[1] + newline + "".join(f" {key}[{i}]: {v}{newline}" for i, v in enumerate(values)), block, count=1)


def read_sii(path: Path, decryptor: Path | None) -> str:
    data = path.read_bytes()
    if data.startswith((b"SiiNunit", b"\xef\xbb\xbfSiiNunit")):
        return data.decode("utf-8-sig")
    if not decryptor or not decryptor.is_file():
        raise ValueError("This save is encrypted. Set the path to SII_Decrypt.exe in Settings, or create a text save with g_save_format 2 in ETS2.")
    # Decrypt a private copy. The installed decryptor overwrites its input.
    with tempfile.TemporaryDirectory(prefix="ets-garage-sii-") as temporary:
        target = Path(temporary) / path.name
        target.write_bytes(data)
        result = subprocess.run([str(decryptor), "-i", target.name], cwd=temporary, capture_output=True, timeout=60,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        output = target.read_bytes()
        if result.returncode or not output.startswith((b"SiiNunit", b"\xef\xbb\xbfSiiNunit")):
            raise ValueError("SII decryption failed: " + (result.stdout + result.stderr).decode("utf-8", errors="replace")[-1500:])
        return output.decode("utf-8-sig")


def game_running() -> bool:
    if os.name != "nt":
        return False
    result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq eurotrucks2.exe", "/FO", "CSV", "/NH"],
                            capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError("Could not check whether ETS2 is running: " + result.stderr.decode(errors="replace"))
    return b'"eurotrucks2.exe"' in result.stdout.lower()


class SaveSession:
    def __init__(self, path: Path, text: str, save_id: str, name: str):
        self.path, self.text, self.save_id, self.name = path, text, save_id, name
        self.session_id = uuid.uuid4().hex
        self.source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        self.bom = path.read_bytes().startswith(b"\xef\xbb\xbf")
        self.matches = list(UNIT.finditer(text))
        self.units = {m[2]: (m[1], m[0]) for m in self.matches}
        if len(self.units) != len(self.matches) or not text.lstrip().startswith("SiiNunit"):
            raise ValueError("Malformed SII save: duplicate units or missing SiiNunit header.")
        self.overrides: dict[str, str] = {}
        self.saved: dict[str, str] = {}
        self.undo_stack: list[dict[str, str]] = []
        self.redo_stack: list[dict[str, str]] = []
        self.revision = 0
        player = next((b for t, b in self.units.values() if t == "player"), None)
        if not player:
            raise ValueError("This file has no player unit.")
        self.truck_ids = refs(player, "trucks")
        if not self.truck_ids:
            raise ValueError("This save has no owned trucks.")
        player_fields = fields(player)
        assigned = player_fields.get("assigned_vehicles")
        current = fields(self.units[assigned][1]).get("vehicle") if assigned in self.units else player_fields.get("my_truck")
        self.truck_id = current if current in self.truck_ids else self.truck_ids[0]
        self.validate(self.overrides)

    def block(self, unit_id: str, overrides: dict | None = None) -> str:
        changes = self.overrides if overrides is None else overrides
        if unit_id in changes:
            return changes[unit_id]
        return self.units[unit_id][1]

    def validate(self, changes: dict) -> None:
        # Validate owned accessory lists, including counts and paired hookup arrays.
        for truck_id in self.truck_ids:
            truck = self.block(truck_id, changes)
            ids = refs(truck, "accessories")
            if len(ids) != len(set(ids)):
                raise ValueError("An accessory unit cannot occur twice. Duplicate it to create an independent instance.")
            for accessory_id in ids:
                if accessory_id not in changes and accessory_id not in self.units:
                    raise ValueError(f"Missing accessory unit {accessory_id}.")
                block = self.block(accessory_id, changes)
                if not UNIT.fullmatch(block) or "accessory" not in UNIT.match(block)[1]:
                    raise ValueError(f"Invalid accessory unit {accessory_id}.")
                data = fields(block)
                if not unquote(data.get("data_path", '""')).startswith("/def/"):
                    raise ValueError(f"Invalid definition path on {accessory_id}.")
                names, hookups = refs(block, "slot_name"), refs(block, "slot_hookup")
                if len(names) != len(hookups):
                    raise ValueError(f"Attachment names and hookups differ on {accessory_id}.")

    def state(self) -> dict:
        trucks = []
        active = None
        for truck_id in self.truck_ids:
            block = self.block(truck_id)
            data = fields(block)
            accessories = []
            for unit_id in refs(block, "accessories"):
                accessory = self.block(unit_id)
                values = fields(accessory)
                path = unquote(values["data_path"])
                accessories.append({"id": unit_id, "type": UNIT.match(accessory)[1], "dataPath": path,
                                    "category": category(path), "fields": values,
                                    "slots": [{"name": unquote(n), "hookup": unquote(h)} for n, h in zip(refs(accessory, "slot_name"), refs(accessory, "slot_hookup"))]})
            cabin = next((a for a in accessories if a["category"] == "cabin"), None)
            brand = cabin["dataPath"].split("/")[4] if cabin else "unknown"
            plate = re.sub(r"<[^>]+>", "", unquote(data.get("license_plate", '""')).split("|")[0]).strip().rstrip(".")
            truck = {"id": truck_id, "name": brand.replace(".", " ").replace("_", " ").title(),
                     "brand": brand, "plate": plate, "accessoryCount": len(accessories), "selected": truck_id == self.truck_id}
            trucks.append(truck)
            if truck_id == self.truck_id:
                active = {**truck, "accessories": accessories}
        return {"sessionId": self.session_id, "saveId": self.save_id, "saveName": self.name,
                "trucks": trucks, "truck": active, "canUndo": bool(self.undo_stack), "canRedo": bool(self.redo_stack),
                "dirty": self.overrides != self.saved, "revision": self.revision}

    def edit(self, request: dict, catalog: dict[str, dict]) -> dict:
        truck_id = request.get("truckId", self.truck_id)
        if truck_id not in self.truck_ids:
            raise ValueError("Choose an owned truck from this save.")
        changes = dict(self.overrides)
        truck = self.block(truck_id)
        ids = refs(truck, "accessories")
        op, unit_id = request["op"], request.get("accessoryId")
        if op != "add" and unit_id not in ids:
            raise ValueError("Choose an accessory from the selected truck.")
        block = self.block(unit_id) if unit_id else ""
        new_id = "_nameless.e75." + uuid.uuid4().hex[:8] + ".0001"
        if op in ("replace", "fields", "hookup") and any(
            other_id != truck_id and re.search(r"^[ \t]+accessories\[\d+\]: " + re.escape(unit_id) + r"\r?$", self.block(other_id), re.M)
            for other_id in self.units if self.units[other_id][0] in ("vehicle", "trailer", "bus")
        ):
            # Copy on write protects another vehicle that shares this accessory unit.
            ids[ids.index(unit_id)] = new_id
            block = re.sub(r"^(\w+)\s*:\s*[\w.]+", lambda m: f"{m[1]} : {new_id}", block, count=1)
            unit_id = new_id
            changes[truck_id] = set_array(truck, "accessories", ids)
        if op in ("replace", "add"):
            definition = catalog.get(request.get("dataPath"))
            if not definition:
                raise ValueError("Definition is not in the installed game catalog.")
            path = definition["path"]
            if definition.get("category") == "hookup":
                raise ValueError("Install a hookup on a named attachment point.")
            if op == "replace":
                if category(path) != category(unquote(fields(block)["data_path"])):
                    raise ValueError("Replace with the same part category, or add a separate accessory.")
                changes[unit_id] = set_field(block, "data_path", json.dumps(path))
            else:
                kind = category(path)
                source = next((self.block(i) for i in ids if category(unquote(fields(self.block(i))["data_path"])) == kind), None)
                if source:
                    # A donor supplies type-specific fields such as wheel offsets or paint colors.
                    block = re.sub(r"^(\w+)\s*:\s*[\w.]+", lambda m: f"{m[1]} : {new_id}", source, count=1)
                    block = set_field(block, "data_path", json.dumps(path))
                    if "slot_name" in fields(block):
                        block = set_array(set_array(block, "slot_name", []), "slot_hookup", [])
                else:
                    if kind in ("cabin", "chassis", "engine", "transmission", "interior", "head_light", "truck"):
                        accessory_type, extra = "vehicle_accessory", ""
                    elif kind == "paint_job" or kind.startswith(("f_", "r_")) and any(x in kind for x in ("tire", "disc", "hub", "nuts", "cover", "rim")):
                        raise ValueError("Add this part by duplicating an installed part of the same category, so its paint or axle fields are preserved.")
                    else:
                        accessory_type, extra = "vehicle_addon_accessory", " slot_name: 0\n slot_hookup: 0\n paint_color: (1, 1, 1)\n"
                    block = f'{accessory_type} : {new_id} {{\n{extra} data_path: {json.dumps(path)}\n refund: 0\n}}'
                changes[new_id] = block
                ids.append(new_id)
                changes[truck_id] = set_array(truck, "accessories", ids)
        elif op == "duplicate":
            changes[new_id] = re.sub(r"^(\w+)\s*:\s*[\w.]+", lambda m: f"{m[1]} : {new_id}", block, count=1)
            ids.insert(ids.index(unit_id) + 1, new_id)
            changes[truck_id] = set_array(truck, "accessories", ids)
        elif op == "remove":
            kind = category(unquote(fields(block)["data_path"]))
            if kind in ("cabin", "chassis", "engine", "transmission", "interior", "paint_job", "truck") and sum(category(unquote(fields(self.block(i))["data_path"])) == kind for i in ids) == 1:
                raise ValueError(f"Keep at least one {kind.replace('_', ' ')} on the truck.")
            ids.remove(unit_id)
            changes[truck_id] = set_array(truck, "accessories", ids)
            # Keep shared units, but remove an unowned accessory completely.
            referenced = any(unit_id in fields(self.block(owner, changes)).values()
                             for owner in self.units.keys() | changes.keys() if owner != unit_id)
            if not referenced:
                if unit_id in self.units:
                    changes[unit_id] = ""
                else:
                    changes.pop(unit_id, None)
        elif op == "fields":
            current = fields(block)
            for key, value in request.get("fields", {}).items():
                if key not in current or key in ("data_path", "slot_name", "slot_hookup") or key.startswith(("slot_name[", "slot_hookup[")):
                    raise ValueError("Use the part picker and attachment editor for definition paths and hookups. Other editable fields must already exist.")
                if not isinstance(value, str) or not re.fullmatch(r'(?:"(?:[^"\\\r\n]|\\[^\r\n])*"|\([^{}\r\n]*\)|[\w.&+\-]+)', value):
                    raise ValueError(f"Invalid single-line SII value for {key}.")
                if value.startswith("(") and not re.fullmatch(r"\(\s*[\d.eE&+\-a-fA-F]+(?:\s*,\s*[\d.eE&+\-a-fA-F]+)*\s*\)", value):
                    raise ValueError("Tuple fields must contain numeric components.")
                block = set_field(block, key, value)
            changes[unit_id] = block
        elif op == "hookup":
            if "slot_name" not in fields(block):
                raise ValueError("This accessory has no hookup array.")
            names, hookups = refs(block, "slot_name"), refs(block, "slot_hookup")
            slot = request["slotName"]
            if not re.fullmatch(r"[\w.-]+", slot):
                raise ValueError("Invalid locator name.")
            value = request.get("hookup", "")
            if value and not re.fullmatch(r"[\w.-]+", value):
                raise ValueError("Invalid hookup unit name.")
            index = request.get("index")
            if index is not None:
                if not isinstance(index, int) or index < 0 or index >= len(names) or unquote(names[index]) != slot:
                    raise ValueError("Attachment entry changed. Select it again.")
            else:
                index = next((i for i, name in enumerate(names) if unquote(name) == slot), None)
            if not value:
                if index is not None:
                    names.pop(index)
                    hookups.pop(index)
            elif index is None or request.get("duplicate"):
                names.append(json.dumps(slot))
                hookups.append(value)
            else:
                hookups[index] = value
            changes[unit_id] = set_array(set_array(block, "slot_name", names), "slot_hookup", hookups)
        else:
            raise ValueError("Unknown edit operation.")
        self.validate(changes)
        if changes != self.overrides:
            self.undo_stack.append(self.overrides)
            self.redo_stack.clear()
            self.overrides = changes
            self.revision += 1
        self.truck_id = truck_id
        return {**self.state(), "editedAccessoryId": new_id if op in ("add", "duplicate") else unit_id if op != "remove" else None}

    def history(self, redo: bool = False) -> dict:
        source, target = (self.redo_stack, self.undo_stack) if redo else (self.undo_stack, self.redo_stack)
        if source:
            target.append(self.overrides)
            self.overrides = source.pop()
            self.revision += 1
        return self.state()

    def render(self) -> str:
        output, cursor = [], 0
        for match in self.matches:
            output.extend((self.text[cursor:match.start()], self.overrides.get(match[2], match[0])))
            cursor = match.end()
        output.append(self.text[cursor:])
        text = "".join(output)
        additions = [block for unit_id, block in self.overrides.items() if unit_id not in self.units]
        if additions:
            end = text.rfind("}")
            text = text[:end] + "\n" + "\n\n".join(additions) + "\n" + text[end:]
        return text

    def save(self) -> dict:
        if game_running():
            raise ValueError("Close ETS2 before writing this save. Then load it in the game after saving.")
        if hashlib.sha256(self.path.read_bytes()).hexdigest() != self.source_hash:
            raise ValueError("The save changed outside the garage. Reload it before writing.")
        self.validate(self.overrides)
        if self.overrides == self.saved:
            return {"state": self.state(), "savePath": str(self.path), "backupPath": None}
        rendered = self.render()
        units = {match[2]: (match[1], match[0]) for match in UNIT.finditer(rendered)}
        economies = {unit_id for unit_id, (kind, _) in units.items() if kind == "economy"}
        if economies:
            referenced = {value for _, block in units.values() for value in fields(block).values() if value in units}
            roots = {unit_id for unit_id in units if unit_id.startswith("_nameless.") and unit_id not in referenced}
            if len(economies) != 1 or roots != economies:
                raise ValueError("The save contains disconnected unit trees. No files were written.")
        data = rendered.encode("utf-8")
        if self.bom:
            data = b"\xef\xbb\xbf" + data
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = self.path.parent / "garage-backups" / stamp
        backup.mkdir(parents=True)
        # A full save-folder backup retains metadata and optional preview files.
        for original in self.path.parent.iterdir():
            if original.is_file():
                shutil.copy2(original, backup / original.name)
        temporary = self.path.with_name("game.sii.garage-" + uuid.uuid4().hex + ".tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            # Check again after backup and preparation to catch game/cloud writes.
            if hashlib.sha256(self.path.read_bytes()).hexdigest() != self.source_hash:
                raise ValueError("The save changed while preparing the write. The garage did not replace it.")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
        self.source_hash = hashlib.sha256(data).hexdigest()
        self.saved = dict(self.overrides)
        return {"state": self.state(), "savePath": str(self.path), "backupPath": str(backup)}
