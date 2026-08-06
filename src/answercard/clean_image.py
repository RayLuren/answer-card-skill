from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import struct
import zlib


DEFAULT_THRESHOLD = 195
SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png"}


class CleanImageError(RuntimeError):
    """A user-facing clean-image preparation failure."""


@dataclass(frozen=True)
class CleanImageResult:
    output_path: Path
    sha256: str
    created: bool


def clean_output_path(source: str | Path) -> Path:
    """Return the required sibling ``<source-stem>-clean.png`` path."""

    path = Path(source)
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise CleanImageError("source image must be a PNG, JPG, or JPEG file")
    if path.stem.lower().endswith("-clean"):
        raise CleanImageError("source image must not already end with -clean")
    return path.with_name(f"{path.stem}-clean.png")


def prepare_clean_image(
    source: str | Path,
    *,
    threshold: int = DEFAULT_THRESHOLD,
) -> CleanImageResult:
    """Create a deterministic black/white clean PNG without changing the source.

    Transparent pixels are composited onto white, the image is converted to
    luminance, and pixels below ``threshold`` become black while all others
    become white. Existing differing output is never overwritten.
    """

    source_path = Path(source)
    output_path = clean_output_path(source_path)
    if not source_path.is_file():
        raise CleanImageError(f"source image not found: {source_path}")
    if not 1 <= threshold <= 254:
        raise CleanImageError("threshold must be between 1 and 254")

    try:
        from PIL import Image
    except ImportError as exc:
        raise CleanImageError(
            "Pillow is required to prepare clean images. Install project dependencies first."
        ) from exc

    try:
        with Image.open(source_path) as opened:
            rgba = opened.convert("RGBA")
            white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            composited = Image.alpha_composite(white, rgba).convert("L")
            cleaned = composited.point(lambda value: 0 if value < threshold else 255, mode="1").convert("RGB")
            payload = _encode_stable_rgb_png(cleaned.size, cleaned.tobytes())
    except (OSError, ValueError) as exc:
        raise CleanImageError(f"failed to decode or clean {source_path}: {exc}") from exc

    digest = hashlib.sha256(payload).hexdigest()
    if output_path.exists():
        if not output_path.is_file():
            raise CleanImageError(f"clean output path is not a file: {output_path}")
        existing_digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
        if existing_digest != digest:
            raise CleanImageError(
                f"clean output already exists with different content; refusing to overwrite: {output_path}"
            )
        return CleanImageResult(output_path=output_path, sha256=digest, created=False)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        raise CleanImageError(f"clean output appeared during creation; refusing to overwrite: {output_path}") from None
    except OSError as exc:
        try:
            output_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise CleanImageError(f"failed to write clean output {output_path}: {exc}") from exc

    return CleanImageResult(output_path=output_path, sha256=digest, created=True)


def _encode_stable_rgb_png(size: tuple[int, int], pixels: bytes) -> bytes:
    """Encode filter-0 RGB rows with deterministic stored DEFLATE blocks."""

    width, height = size
    row_bytes = width * 3
    if len(pixels) != row_bytes * height:
        raise ValueError("RGB pixel payload does not match image dimensions")
    raw = b"".join(b"\x00" + pixels[offset : offset + row_bytes] for offset in range(0, len(pixels), row_bytes))

    blocks: list[bytes] = []
    for offset in range(0, len(raw), 65535):
        block = raw[offset : offset + 65535]
        final = 1 if offset + len(block) == len(raw) else 0
        length = len(block)
        blocks.append(bytes([final]) + struct.pack("<HH", length, length ^ 0xFFFF) + block)
    compressed = b"\x78\x01" + b"".join(blocks) + struct.pack(">I", zlib.adler32(raw) & 0xFFFFFFFF)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", compressed) + chunk(b"IEND", b"")
