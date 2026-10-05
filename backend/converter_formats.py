"""Read the converter's binary geometry and indexed definition bundles."""
from __future__ import annotations

import array
import json
import math
import os
from pathlib import Path
import re
import struct
import sys
from typing import Iterable, Iterator


DEFINITION_BUNDLE_MAGIC = b"SGDEFB1\0"
_RECORD_HEADER = struct.Struct("<IQ")
_MAX_PATH_BYTES = 1024 * 1024
_READ_CHUNK_BYTES = 1024 * 1024
_SCALAR_TYPES = {"f32": ("f", 4), "u32": ("I", 4), "u8": ("B", 1)}


def _skip_bytes(handle, count: int) -> None:
    while count:
        chunk = handle.read(min(count, _READ_CHUNK_BYTES))
        if not chunk:
            raise ValueError("Truncated definition bundle content")
        count -= len(chunk)


def _integer(value, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def _finite_vector(value, count: int, label: str) -> None:
    if not isinstance(value, list) or len(value) != count:
        raise ValueError(f"{label} must contain {count} numbers")
    try:
        valid = all(type(number) in (int, float) and math.isfinite(number) for number in value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"{label} contains a non-finite or invalid number")


def _indexed_records(value, label: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    for index, record in enumerate(value):
        if not isinstance(record, dict) or type(record.get("index")) is not int or record["index"] != index:
            raise ValueError(f"{label} indices must match their array positions")
    return value


def _read_descriptor(handle, descriptor, binary_bytes: int, label: str, components: int | None = None,
                     scalar_type: str | None = None, scalar_count: int | None = None) -> list:
    if not isinstance(descriptor, dict):
        raise ValueError(f"{label} must be a stream descriptor")
    offset = _integer(descriptor.get("offset"), f"{label}.offset")
    count = _integer(descriptor.get("count"), f"{label}.count")
    width = _integer(descriptor.get("components"), f"{label}.components", 1)
    kind = descriptor.get("type")
    if not isinstance(kind, str) or kind not in _SCALAR_TYPES:
        raise ValueError(f"{label} has an unsupported scalar type")
    if components is not None and width != components:
        raise ValueError(f"{label} must have {components} components")
    if scalar_type is not None and kind != scalar_type:
        raise ValueError(f"{label} must have scalar type {scalar_type}")
    if count % width or scalar_count is not None and count != scalar_count:
        raise ValueError(f"{label} has an invalid scalar count")
    code, scalar_bytes = _SCALAR_TYPES[kind]
    byte_count = count * scalar_bytes
    if offset % scalar_bytes or offset > binary_bytes or byte_count > binary_bytes - offset:
        raise ValueError(f"{label} has an unaligned or out-of-bounds range")
    handle.seek(offset)
    raw = handle.read(byte_count)
    if len(raw) != byte_count:
        raise ValueError(f"{label} is truncated")
    values = array.array(code)
    values.frombytes(raw)
    if sys.byteorder != "little" and scalar_bytes > 1:
        values.byteswap()
    if kind == "f32" and any(not math.isfinite(value) for value in values):
        raise ValueError(f"{label} contains a non-finite float")
    return values.tolist()


def read_viewer_model(path: Path) -> dict:
    """Decode scalar arrays without changing UV aliases, winding, or transforms."""
    path = Path(path)
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid viewer model manifest: {error}") from error
    if not isinstance(metadata, dict) or metadata.get("format") != "SGarageModel" or type(metadata.get("version")) is not int or metadata["version"] != 1:
        raise ValueError("Unsupported viewer model format or version")
    binary_name = metadata.get("binary")
    if not isinstance(binary_name, str) or not binary_name or any(char in binary_name for char in '<>:"/\\|?*') or any(ord(char) < 32 for char in binary_name) or not binary_name.endswith(".sgb"):
        raise ValueError("Viewer model binary must be a sibling .sgb basename")
    binary_path = path.parent / binary_name
    if binary_path.resolve().parent != path.parent.resolve():
        raise ValueError("Viewer model binary resolves outside the model directory")
    binary_bytes = _integer(metadata.get("binaryBytes"), "binaryBytes")
    materials = metadata.get("materials")
    if not isinstance(materials, list) or any(not isinstance(item, dict) or not isinstance(item.get("alias"), str) or not isinstance(item.get("effect"), str) for item in materials):
        raise ValueError("materials must contain alias/effect records")
    pieces = _indexed_records(metadata.get("pieces"), "pieces")
    locators = _indexed_records(metadata.get("locators"), "locators")
    bones = _indexed_records(metadata.get("bones"), "bones")
    parts = metadata.get("parts")
    if not isinstance(parts, list):
        raise ValueError("parts must be an array")
    for part in parts:
        if not isinstance(part, dict) or not isinstance(part.get("name"), str):
            raise ValueError("parts must contain named records")
        for key, records in (("pieces", pieces), ("locators", locators)):
            references = part.get(key)
            if not isinstance(references, list) or any(type(index) is not int or not 0 <= index < len(records) for index in references):
                raise ValueError(f"part {key} references an invalid index")
    for locator in locators:
        if not isinstance(locator.get("name"), str) or locator.get("hookup") is not None and not isinstance(locator["hookup"], str):
            raise ValueError("locator name/hookup must be strings")
        for key, count in (("position", 3), ("rotation", 4), ("scale", 3)):
            _finite_vector(locator.get(key), count, f"locator {locator['index']}.{key}")
    for bone in bones:
        if not isinstance(bone.get("name"), str):
            raise ValueError("bone name must be a string")
        parent = _integer(bone.get("parent"), "bone.parent")
        if parent != 255 and (parent >= len(bones) or parent == bone["index"]):
            raise ValueError("bone parent references an invalid index")
        for key, count in (("matrix", 16), ("inverseMatrix", 16), ("translation", 3), ("rotation", 4), ("scale", 3), ("stretch", 4)):
            _finite_vector(bone.get(key), count, f"bone {bone['index']}.{key}")
        _finite_vector([bone.get("determinantSign")], 1, "bone determinantSign")
    with binary_path.open("rb") as handle:
        if os.fstat(handle.fileno()).st_size != binary_bytes:
            raise ValueError("Viewer model binary size does not match binaryBytes")
        for piece in pieces:
            label = f"piece {piece['index']}"
            vertices = _integer(piece.get("vertexCount"), f"{label}.vertexCount")
            material = _integer(piece.get("material"), f"{label}.material", -(2 ** 31))
            if material >= 2 ** 31:
                raise ValueError(f"{label} material must fit a signed 32-bit integer")
            bone_count = _integer(piece.get("boneCount"), f"{label}.boneCount")
            if bone_count > 8:
                raise ValueError(f"{label} exceeds the eight bone slots supported by the converter")
            streams = piece.get("streams")
            if not isinstance(streams, dict) or "_POSITION" not in streams:
                raise ValueError(f"{label} is missing its position stream")
            aliases = piece.get("uvAliases")
            if not isinstance(aliases, dict) or any(key not in streams or re.fullmatch(r"_UV\d+", key) is None or not isinstance(value, list) or any(not isinstance(alias, str) for alias in value) for key, value in aliases.items()):
                raise ValueError(f"{label} contains invalid UV aliases")
            decoded = {}
            for tag, descriptor in streams.items():
                width, kind = None, None
                if tag in ("_POSITION", "_NORMAL"):
                    width, kind = 3, "f32"
                elif re.fullmatch(r"_UV\d+", tag):
                    width, kind = 2, "f32"
                elif tag in ("_TANGENT", "_RGBA", "_FACTOR"):
                    width, kind = 4, "f32"
                elif tag in ("_BONE_INDEX", "_BONE_WEIGHT"):
                    if not bone_count:
                        raise ValueError(f"{label} has skin streams without bone slots")
                    width, kind = bone_count, "u8"
                if not isinstance(descriptor, dict):
                    raise ValueError(f"{label}.{tag} must be a stream descriptor")
                actual_width = _integer(descriptor.get("components"), f"{label}.{tag}.components", 1)
                decoded[tag] = _read_descriptor(handle, descriptor, binary_bytes, f"{label}.{tag}", width, kind, vertices * actual_width)
            if bone_count and not {"_BONE_INDEX", "_BONE_WEIGHT"}.issubset(decoded):
                raise ValueError(f"{label} is missing skin streams")
            if bone_count and any(weight and index >= len(bones) for index, weight in zip(decoded["_BONE_INDEX"], decoded["_BONE_WEIGHT"])):
                raise ValueError(f"{label} references an invalid bone")
            indices = _read_descriptor(handle, piece.get("indices"), binary_bytes, f"{label}.indices", 1, "u32")
            if len(indices) % 3 or any(index >= vertices for index in indices):
                raise ValueError(f"{label} contains invalid triangle indices")
            piece["streams"] = decoded
            piece["indices"] = indices
    return metadata


class DefinitionBundle:
    """Index definitions by byte range and read their content only when requested."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.entries: dict[str, tuple[int, int]] = {}
        with self.path.open("rb") as handle:
            self._signature = self._file_signature(handle)
            size = self._signature[2]
            if handle.read(len(DEFINITION_BUNDLE_MAGIC)) != DEFINITION_BUNDLE_MAGIC:
                raise ValueError("Invalid definition bundle magic")
            while handle.tell() < size:
                header = handle.read(_RECORD_HEADER.size)
                if len(header) != _RECORD_HEADER.size:
                    raise ValueError("Truncated definition bundle record header")
                path_bytes, data_bytes = _RECORD_HEADER.unpack(header)
                if not 0 < path_bytes <= _MAX_PATH_BYTES or path_bytes > size - handle.tell():
                    raise ValueError("Invalid definition bundle path length")
                try:
                    virtual_path = handle.read(path_bytes).decode("utf-8")
                except UnicodeError as error:
                    raise ValueError("Definition bundle path is not UTF-8") from error
                if not virtual_path.startswith("/") or any(char in virtual_path for char in "\\:\0") or any(part in ("", ".", "..") for part in virtual_path[1:].split("/")):
                    raise ValueError("Unsafe definition bundle virtual path")
                if virtual_path in self.entries:
                    raise ValueError(f"Duplicate definition bundle path: {virtual_path}")
                offset = handle.tell()
                if data_bytes > size - offset:
                    raise ValueError("Truncated definition bundle record content")
                self.entries[virtual_path] = offset, data_bytes
                _skip_bytes(handle, data_bytes)
            if self._file_signature(handle) != self._signature:
                raise ValueError("Definition bundle changed while indexing")

    @staticmethod
    def _file_signature(handle) -> tuple:
        stat = os.fstat(handle.fileno())
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(self.entries)

    def __contains__(self, virtual_path: str) -> bool:
        return virtual_path in self.entries

    def read_text(self, virtual_path: str) -> str:
        return next(self.iter_texts((virtual_path,)))[1]

    def iter_texts(self, paths: Iterable[str] | None = None) -> Iterator[tuple[str, str]]:
        with self.path.open("rb") as handle:
            if self._file_signature(handle) != self._signature:
                raise ValueError("Definition bundle changed after indexing")
            started = False
            for virtual_path in self.entries if paths is None else paths:
                offset, size = self.entries[virtual_path]
                remaining = offset - handle.tell()
                if started and 0 <= remaining <= _READ_CHUNK_BYTES:
                    _skip_bytes(handle, remaining)
                else:
                    handle.seek(offset)
                started = True
                content = handle.read(size)
                if len(content) != size or self._file_signature(handle) != self._signature:
                    raise ValueError("Definition bundle changed while reading")
                yield virtual_path, content.decode("utf-8", errors="replace")
