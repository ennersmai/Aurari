#!/usr/bin/env python3
"""
VRMA Animation Generator for Aura

Generates additional VRMA animation files by modifying existing ones.
VRMA files are glTF-based animation containers (GLB format). This script:
1. Reads existing VRMA files (binary GLB)
2. Modifies animation timing (keyframe timestamps in binary buffer)
3. Optionally modifies amplitude (translation/scale values in binary buffer)
4. Saves as new VRMA files with descriptive names

CRITICAL FIX (v2): Previous version only modified accessor min/max metadata,
NOT the actual binary keyframe data. The actual float32 time values live in
the BIN chunk. This version properly reads and modifies those binary values.

Usage:
    python generate_vrma_animations.py [--input-dir INPUT_DIR] [--output-dir OUTPUT_DIR]
    python generate_vrma_animations.py --force   # Re-generate even if files exist
"""

import argparse
import copy
import json
import math
import os
import struct
import sys
from pathlib import Path
from typing import Any


# ---- VRMA Binary Format Helpers -----------------------------------------

def read_vrma(filepath: str) -> bytes:
    """Read a VRMA file as raw bytes."""
    with open(filepath, "rb") as f:
        return f.read()


def write_vrma(filepath: str, data: bytes) -> None:
    """Write raw bytes to a VRMA file."""
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "wb") as f:
        f.write(data)


def is_glb(data: bytes) -> bool:
    """Check if data is a GLB (binary glTF) file."""
    return len(data) >= 12 and data[:4] == b"glTF"


def parse_glb(data: bytes) -> dict[str, Any]:
    """
    Parse a GLB file into its JSON header and binary chunks.
    Returns {"json": dict, "bin": bytes}.
    """
    if not is_glb(data):
        raise ValueError("Not a valid GLB file")

    # GLB Header: magic(4) + version(4) + length(4)
    version = struct.unpack_from("<I", data, 4)[0]
    total_length = struct.unpack_from("<I", data, 8)[0]

    offset = 12
    json_data = None
    bin_data = b""

    while offset < total_length:
        chunk_length = struct.unpack_from("<I", data, offset)[0]
        chunk_type = struct.unpack_from("<I", data, offset + 4)[0]
        chunk_data = data[offset + 8 : offset + 8 + chunk_length]

        if chunk_type == 0x4E4F534A:  # "JSON"
            json_data = json.loads(chunk_data.decode("utf-8"))
        elif chunk_type == 0x004E4942:  # "BIN\0"
            bin_data = chunk_data

        offset += 8 + chunk_length

    if json_data is None:
        raise ValueError("GLB file has no JSON chunk")

    return {"json": json_data, "bin": bin_data}


def build_glb(gltf_json: dict[str, Any], bin_data: bytes) -> bytes:
    """Build a GLB file from JSON and binary data."""
    json_str = json.dumps(gltf_json, separators=(",", ":"))
    json_bytes = json_str.encode("utf-8")

    # Pad JSON to 4-byte alignment
    while len(json_bytes) % 4 != 0:
        json_bytes += b" "

    # Pad BIN to 4-byte alignment
    bin_padded = bin_data
    while len(bin_padded) % 4 != 0:
        bin_padded += b"\x00"

    # GLB Header
    total_length = 12 + 8 + len(json_bytes) + (8 + len(bin_padded) if bin_padded else 0)
    header = struct.pack("<III", 0x46546C67, 2, total_length)  # magic="glTF", version=2

    # JSON chunk
    json_chunk = struct.pack("<II", len(json_bytes), 0x4E4F534A) + json_bytes

    result = header + json_chunk

    # BIN chunk (only if non-empty)
    if bin_padded:
        bin_chunk = struct.pack("<II", len(bin_padded), 0x004E4942) + bin_padded
        result += bin_chunk

    return result


# ---- Binary buffer accessor helpers ------------------------------------

def _get_accessor_byte_range(gltf: dict[str, Any], accessor_idx: int) -> tuple[int, int, int]:
    """
    Return (byte_offset, byte_length, component_count) for an accessor.

    component_count is the number of float32 scalars in the accessor
    (count * components_per_element for the type).
    """
    accessor = gltf["accessors"][accessor_idx]
    buffer_view_idx = accessor.get("bufferView")
    if buffer_view_idx is None:
        return -1, 0, 0

    buffer_view = gltf["bufferViews"][buffer_view_idx]
    base_offset = buffer_view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    count = accessor.get("count", 0)

    # Components per element
    type_map = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
    components = type_map.get(accessor.get("type", "SCALAR"), 1)
    total_components = count * components

    byte_length = total_components * 4  # All are FLOAT (componentType 5126)
    return base_offset, byte_length, total_components


def _scale_float32_array(
    bin_array: bytearray,
    byte_offset: int,
    total_floats: int,
    factor: float,
) -> None:
    """Multiply each float32 in the binary buffer section by `factor`."""
    for i in range(total_floats):
        pos = byte_offset + i * 4
        if pos + 4 > len(bin_array):
            break
        val = struct.unpack_from("<f", bin_array, pos)[0]
        struct.pack_into("<f", bin_array, pos, val * factor)


def _lerp_quaternion_toward_identity(
    bin_array: bytearray,
    byte_offset: int,
    count: int,
    blend: float,        # 0 = keep original, 1 = full identity
) -> None:
    """
    Blend each quaternion in the accessor toward the identity quaternion (0, 0, 0, 1).

    blend=0.5 halves the rotation angle, producing a subtle version of the animation.
    blend values > 1 exaggerate (moves AWAY from identity).
    """
    identity = (0.0, 0.0, 0.0, 1.0)
    for i in range(count):
        pos = byte_offset + i * 16  # 4 floats each
        if pos + 16 > len(bin_array):
            break
        q = struct.unpack_from("<4f", bin_array, pos)
        # Lerp each component; for quaternions we should slerp, but lerp + normalize
        # is a good approximation for small rotations.
        blended = tuple(q[j] + (identity[j] - q[j]) * blend for j in range(4))
        # Normalize
        mag = math.sqrt(sum(v * v for v in blended))
        if mag > 1e-6:
            blended = tuple(v / mag for v in blended)
        struct.pack_into("<4f", bin_array, pos, *blended)


# ---- Animation Modifiers (FIXED: now modifies actual binary data) -------

def speed_up_animation(
    gltf: dict[str, Any],
    bin_data: bytes,
    factor: float = 1.5,
) -> tuple[dict[str, Any], bytes]:
    """
    Speed up animation by dividing all time-keyframe values by `factor`.

    factor=1.5 → 50% faster  |  factor=2.0 → twice as fast
    This modifies the actual float32 timestamp values in the binary buffer,
    NOT just the JSON metadata min/max (which was the old broken approach).
    """
    if "animations" not in gltf or not bin_data:
        return gltf, bin_data

    bin_array = bytearray(bin_data)
    seen_input_accessors: set[int] = set()

    for anim in gltf["animations"]:
        for sampler in anim.get("samplers", []):
            input_idx = sampler.get("input")
            if input_idx is None or input_idx in seen_input_accessors:
                continue
            seen_input_accessors.add(input_idx)

            accessor = gltf["accessors"][input_idx]
            if accessor.get("type") != "SCALAR" or accessor.get("componentType") != 5126:
                continue

            byte_offset, _, total_floats = _get_accessor_byte_range(gltf, input_idx)
            if byte_offset < 0 or total_floats == 0:
                continue

            _scale_float32_array(bin_array, byte_offset, total_floats, 1.0 / factor)

            # Update metadata
            if "min" in accessor:
                accessor["min"] = [v / factor for v in accessor["min"]]
            if "max" in accessor:
                accessor["max"] = [v / factor for v in accessor["max"]]

    return gltf, bytes(bin_array)


def slow_down_animation(
    gltf: dict[str, Any],
    bin_data: bytes,
    factor: float = 0.6,
) -> tuple[dict[str, Any], bytes]:
    """
    Slow down animation by multiplying all time-keyframe values by `1/factor`.

    factor=0.5 → half speed  |  factor=0.4 → very slow
    """
    return speed_up_animation(gltf, bin_data, factor)


def reduce_amplitude(
    gltf: dict[str, Any],
    bin_data: bytes,
    blend: float = 0.4,
) -> tuple[dict[str, Any], bytes]:
    """
    Reduce animation amplitude by blending all rotations toward identity.

    blend=0.5 → half the rotation angle (subtle)
    blend=0.8 → very subtle
    """
    if "animations" not in gltf or not bin_data:
        return gltf, bin_data

    bin_array = bytearray(bin_data)
    seen_output_accessors: set[int] = set()

    for anim in gltf["animations"]:
        for sampler in anim.get("samplers", []):
            output_idx = sampler.get("output")
            if output_idx is None or output_idx in seen_output_accessors:
                continue
            seen_output_accessors.add(output_idx)

            accessor = gltf["accessors"][output_idx]
            if accessor.get("componentType") != 5126:  # Must be FLOAT
                continue

            acc_type = accessor.get("type", "")
            count = accessor.get("count", 0)
            byte_offset, _, _ = _get_accessor_byte_range(gltf, output_idx)
            if byte_offset < 0 or count == 0:
                continue

            if acc_type == "VEC4":
                # Quaternion — blend toward identity
                _lerp_quaternion_toward_identity(bin_array, byte_offset, count, blend)
            elif acc_type in ("VEC3", "SCALAR"):
                # Translation/scale — scale toward zero
                components = 3 if acc_type == "VEC3" else 1
                _scale_float32_array(bin_array, byte_offset, count * components, 1.0 - blend)

    return gltf, bytes(bin_array)


def increase_amplitude(
    gltf: dict[str, Any],
    bin_data: bytes,
    factor: float = 1.5,
) -> tuple[dict[str, Any], bytes]:
    """
    Increase animation amplitude by scaling rotation differences away from identity.

    factor=1.5 → 50% larger rotations (more exaggerated)
    """
    if "animations" not in gltf or not bin_data:
        return gltf, bin_data

    bin_array = bytearray(bin_data)
    seen_output_accessors: set[int] = set()

    for anim in gltf["animations"]:
        for sampler in anim.get("samplers", []):
            output_idx = sampler.get("output")
            if output_idx is None or output_idx in seen_output_accessors:
                continue
            seen_output_accessors.add(output_idx)

            accessor = gltf["accessors"][output_idx]
            if accessor.get("componentType") != 5126:
                continue

            acc_type = accessor.get("type", "")
            count = accessor.get("count", 0)
            byte_offset, _, _ = _get_accessor_byte_range(gltf, output_idx)
            if byte_offset < 0 or count == 0:
                continue

            if acc_type == "VEC4":
                # Quaternion — exaggerate by blending AWAY from identity (negative blend)
                # blend = -(factor - 1) moves away from identity
                _lerp_quaternion_toward_identity(bin_array, byte_offset, count, -(factor - 1.0))
            elif acc_type in ("VEC3", "SCALAR"):
                components = 3 if acc_type == "VEC3" else 1
                _scale_float32_array(bin_array, byte_offset, count * components, factor)

    return gltf, bytes(bin_array)


def mirror_animation(
    gltf: dict[str, Any],
    bin_data: bytes,
) -> tuple[dict[str, Any], bytes]:
    """
    Mirror animation by negating X-axis translation values.
    Creates left/right variants of asymmetric animations.
    """
    if "animations" not in gltf or not bin_data:
        return gltf, bin_data

    bin_array = bytearray(bin_data)

    for anim in gltf["animations"]:
        for channel in anim.get("channels", []):
            target = channel.get("target", {})
            path = target.get("path", "")
            if path != "translation":
                continue

            sampler_idx = channel.get("sampler")
            if sampler_idx is None:
                continue

            sampler = anim["samplers"][sampler_idx]
            output_idx = sampler.get("output")
            if output_idx is None:
                continue

            accessor = gltf["accessors"][output_idx]
            if accessor.get("type") != "VEC3" or accessor.get("componentType") != 5126:
                continue

            count = accessor.get("count", 0)
            byte_offset, _, _ = _get_accessor_byte_range(gltf, output_idx)
            if byte_offset < 0 or count == 0:
                continue

            # Negate only X component of each VEC3 (3 floats per keyframe)
            for i in range(count):
                pos = byte_offset + i * 12  # 3 floats * 4 bytes
                if pos + 4 > len(bin_array):
                    break
                x_val = struct.unpack_from("<f", bin_array, pos)[0]
                struct.pack_into("<f", bin_array, pos, -x_val)

    return gltf, bytes(bin_array)


# ---- Generation Pipeline ------------------------------------------------

def generate_variants(
    input_dir: str,
    output_dir: str,
    force: bool = False,
) -> list[str]:
    """
    Generate animation variants from existing VRMA files.

    Each variant is defined by (output_name, modifier_fn, description).
    Modifier functions return (modified_json, modified_bin).

    Returns list of created file paths.
    """
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    created: list[str] = []

    # Map of source file → list of (output_name, modifier_fn, description)
    variants: dict[str, list[tuple[str, Any, str]]] = {
        "dance.vrma": [
            (
                "dance_fast.vrma",
                lambda g, b: speed_up_animation(g, b, 1.8),
                "Fast energetic dance (1.8× speed)",
            ),
            (
                "dance_slow.vrma",
                lambda g, b: slow_down_animation(g, b, 0.5),
                "Slow graceful dance (0.5× speed)",
            ),
            (
                "dance_subtle.vrma",
                lambda g, b: reduce_amplitude(g, b, 0.55),
                "Subtle sway dance (55% amplitude reduction)",
            ),
        ],
        "greeting.vrma": [
            (
                "greeting_enthusiastic.vrma",
                lambda g, b: increase_amplitude(g, b, 1.6),
                "Enthusiastic wave (1.6× amplitude)",
            ),
            (
                "greeting_shy.vrma",
                lambda g, b: reduce_amplitude(g, b, 0.6),
                "Shy timid wave (60% amplitude reduction)",
            ),
            (
                "greeting_left.vrma",
                lambda g, b: mirror_animation(g, b),
                "Left-handed wave (mirrored X-axis)",
            ),
        ],
        "idle_loop.vrma": [
            (
                "idle_energetic.vrma",
                lambda g, b: speed_up_animation(increase_amplitude(g, b, 1.3)[0], increase_amplitude(g, b, 1.3)[1], 1.4),
                "Energetic idle bounce (1.4× speed, 1.3× amplitude)",
            ),
            (
                "idle_relaxed.vrma",
                lambda g, b: slow_down_animation(reduce_amplitude(g, b, 0.45)[0], reduce_amplitude(g, b, 0.45)[1], 0.55),
                "Relaxed slow idle (0.55× speed, 45% amplitude reduction)",
            ),
            (
                "idle_curious.vrma",
                lambda g, b: increase_amplitude(g, b, 1.35),
                "Curious leaning idle (1.35× amplitude)",
            ),
        ],
        "peaceSign.vrma": [
            (
                "peaceSign_double.vrma",
                lambda g, b: speed_up_animation(g, b, 1.5),
                "Double peace sign (1.5× speed)",
            ),
            (
                "peaceSign_slow.vrma",
                lambda g, b: slow_down_animation(g, b, 0.5),
                "Slow graceful peace (0.5× speed)",
            ),
        ],
        "spin.vrma": [
            (
                "spin_fast.vrma",
                lambda g, b: speed_up_animation(g, b, 2.0),
                "Rapid excited spin (2× speed)",
            ),
            (
                "spin_slow.vrma",
                lambda g, b: slow_down_animation(g, b, 0.4),
                "Slow dreamy spin (0.4× speed)",
            ),
        ],
        "modelPose.vrma": [
            (
                "modelPose_confident.vrma",
                lambda g, b: increase_amplitude(g, b, 1.5),
                "Confident model pose (1.5× amplitude)",
            ),
            (
                "modelPose_shy.vrma",
                lambda g, b: reduce_amplitude(g, b, 0.55),
                "Shy pose (55% amplitude reduction)",
            ),
        ],
        "squat.vrma": [
            (
                "squat_deep.vrma",
                lambda g, b: increase_amplitude(g, b, 1.4),
                "Deep dejected squat (1.4× amplitude)",
            ),
            (
                "squat_quick.vrma",
                lambda g, b: speed_up_animation(g, b, 1.6),
                "Quick crouch (1.6× speed)",
            ),
        ],
        "shoot.vrma": [
            (
                "shoot_double.vrma",
                lambda g, b: speed_up_animation(g, b, 1.5),
                "Double shoot (1.5× speed)",
            ),
        ],
        "showFullBody.vrma": [
            (
                "showFullBody_confident.vrma",
                lambda g, b: increase_amplitude(g, b, 1.3),
                "Confident full body (1.3× amplitude)",
            ),
        ],
    }

    for source_file, variant_list in variants.items():
        source_path = input_path / source_file
        if not source_path.exists():
            print(f"  ⚠ Source not found: {source_file} — skipping variants")
            continue

        print(f"\n📁 Processing: {source_file}")
        raw = read_vrma(str(source_path))

        try:
            parsed = parse_glb(raw)
        except Exception as e:
            print(f"  ❌ Failed to parse {source_file}: {e}")
            continue

        for out_name, modifier_fn, description in variant_list:
            out_path = output_path / out_name

            if out_path.exists() and not force:
                print(f"  ⏭ {out_name} already exists — skipping (use --force to regenerate)")
                continue

            try:
                modified_json = copy.deepcopy(parsed["json"])
                modified_bin = parsed["bin"]

                modified_json, modified_bin = modifier_fn(modified_json, modified_bin)

                new_glb = build_glb(modified_json, modified_bin)
                write_vrma(str(out_path), new_glb)

                size_kb = len(new_glb) / 1024
                print(f"  ✅ {out_name} ({size_kb:.1f} KB) — {description}")
                created.append(str(out_path))
            except Exception as e:
                print(f"  ❌ Failed to generate {out_name}: {e}")
                import traceback
                traceback.print_exc()

    return created


# ---- Main ---------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate additional VRMA animations for Aura's avatar (v2 — fixes binary keyframe modification)"
    )
    parser.add_argument(
        "--input-dir",
        default="frontend/public/vrm-assets",
        help="Directory containing source VRMA files",
    )
    parser.add_argument(
        "--output-dir",
        default="frontend/public/vrm-assets",
        help="Directory to write generated VRMA files",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-generate files even if they already exist",
    )
    args = parser.parse_args()

    # Resolve paths relative to the project root
    project_root = Path(__file__).resolve().parents[1]
    input_dir = project_root / args.input_dir
    output_dir = project_root / args.output_dir

    print("=" * 60)
    print("🎬 Aura VRMA Animation Generator v2")
    print("   (Fixed: now modifies actual binary keyframe data)")
    print("=" * 60)
    print(f"Input:  {input_dir}")
    print(f"Output: {output_dir}")
    if args.force:
        print("⚡ --force: Re-generating all files")
    print()

    if not input_dir.exists():
        print(f"❌ Input directory not found: {input_dir}")
        sys.exit(1)

    created = generate_variants(str(input_dir), str(output_dir), force=args.force)

    print("\n" + "=" * 60)
    if created:
        print(f"✅ Generated {len(created)} new animation(s):")
        for path in created:
            print(f"   {Path(path).name}")
    else:
        print("ℹ️ No new animations generated (all already exist; use --force to regenerate)")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Restart the frontend dev server to pick up new files")
    print("2. Animations are already registered in animationRouter.ts and l5_animation.py")


if __name__ == "__main__":
    main()
