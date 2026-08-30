import base64
import binascii
import os
import secrets
import stat
from typing import Iterable, Optional


IMAGE_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "webp"})
VIDEO_EXTENSIONS = frozenset({"mp4", "ts", "flv"})


def detect_raster_extension(header: bytes) -> str:
    data = bytes(header or b"")
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    raise ValueError("image content is not a supported raster format")


def _normalized_extension(value: str) -> str:
    extension = str(value or "").strip().lower().lstrip(".")
    if not extension or not extension.isascii() or not extension.isalnum():
        raise ValueError("media extension is invalid")
    return extension


def validate_media_header(header: bytes, extension: str) -> None:
    """Reject active or mislabeled content before a mutable upload is published."""

    data = bytes(header or b"")
    ext = _normalized_extension(extension)
    if ext in ("jpg", "jpeg"):
        valid = data.startswith(b"\xff\xd8\xff")
    elif ext == "png":
        valid = data.startswith(b"\x89PNG\r\n\x1a\n")
    elif ext == "webp":
        valid = len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    elif ext == "mp4":
        valid = len(data) >= 12 and data[4:8] == b"ftyp"
    elif ext == "flv":
        valid = data.startswith(b"FLV")
    elif ext == "ts":
        valid = len(data) >= 1 and data[0] == 0x47
        if valid and len(data) >= 189:
            valid = data[188] == 0x47
    else:
        raise ValueError("media extension is not allowed")

    if not valid:
        raise ValueError("media content does not match its extension")


def decode_base64_limited(value: str, *, max_bytes: int) -> bytes:
    """Strictly decode a bounded base64 or base64 data-URL payload."""

    if max_bytes < 1:
        raise ValueError("base64 size limit is invalid")
    raw = str(value or "").strip()
    if raw.lower().startswith("data:"):
        marker_index = raw.find(",")
        if marker_index < 0 or ";base64" not in raw[:marker_index].lower():
            raise ValueError("data URL must contain base64 media")
        raw = raw[marker_index + 1 :]

    max_encoded_length = ((int(max_bytes) + 2) // 3) * 4
    if not raw or len(raw) > max_encoded_length + 4:
        raise ValueError("base64 media exceeds the maximum size")
    try:
        encoded = raw.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("base64 media must be ASCII") from exc
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("base64 media is invalid") from exc
    if not decoded or len(decoded) > int(max_bytes):
        raise ValueError("base64 media exceeds the maximum size")
    return decoded


def ensure_private_parent(abs_path: str, *, allowed_root: str) -> str:
    """Create and verify the destination parent inside an application storage root."""

    raw_root = str(allowed_root or "").strip()
    raw_target = str(abs_path or "").strip()
    if not raw_root or not raw_target:
        raise ValueError("upload storage path is invalid")
    root = os.path.realpath(os.path.abspath(raw_root))
    target = os.path.abspath(raw_target)
    if os.path.lexists(target) and os.path.islink(target):
        raise ValueError("symbolic links are not allowed for uploads")
    real_target = os.path.realpath(target)
    real_parent = os.path.dirname(real_target)
    if os.path.commonpath((root, real_parent)) != root or os.path.commonpath((root, real_target)) != root:
        raise ValueError("upload path escapes the configured root")

    root_created = not os.path.exists(root)
    os.makedirs(root, mode=0o700, exist_ok=True)
    root_stat = os.lstat(root)
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise ValueError("upload storage root is invalid")
    if root_created and os.name != "nt":
        os.chmod(root, 0o700)  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions

    relative_parent = os.path.relpath(real_parent, root)
    current = root
    if relative_parent != os.curdir:
        for component in relative_parent.split(os.sep):
            if not component or component in (os.curdir, os.pardir):
                raise ValueError("upload storage path is invalid")
            current = os.path.join(current, component)
            try:
                os.mkdir(current, 0o700)
            except FileExistsError:
                pass
            current_stat = os.lstat(current)
            if stat.S_ISLNK(current_stat.st_mode) or not stat.S_ISDIR(current_stat.st_mode):
                raise ValueError("symbolic links are not allowed for uploads")

    real_parent = os.path.realpath(current)
    real_target = os.path.realpath(target)
    if os.path.commonpath((root, real_parent)) != root or os.path.commonpath((root, real_target)) != root:
        raise ValueError("upload path escapes the configured root")
    if os.path.islink(real_parent) or os.path.islink(target):
        raise ValueError("symbolic links are not allowed for uploads")
    if os.name != "nt":
        # Directories need owner execute to remain traversable; no group/world access.
        os.chmod(real_parent, 0o700)  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
    return real_target


def atomic_write_chunks(
    abs_path: str,
    chunks: Iterable[bytes],
    *,
    allowed_root: str,
    max_bytes: int,
    media_extension: Optional[str] = None,
) -> int:
    """Atomically write a bounded stream using a private, no-follow temporary file."""

    if int(max_bytes) < 1:
        raise ValueError("upload size limit is invalid")
    target = ensure_private_parent(abs_path, allowed_root=allowed_root)
    parent = os.path.dirname(target)
    target_name = os.path.basename(target)
    temporary_name = f".{target_name}.{secrets.token_hex(8)}.part"
    temporary = os.path.join(parent, temporary_name)
    descriptor = None
    parent_descriptor = None
    temporary_exists = False
    written = 0
    header = bytearray()
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if os.name != "nt":
            parent_flags = os.O_RDONLY
            if hasattr(os, "O_DIRECTORY"):
                parent_flags |= os.O_DIRECTORY
            if hasattr(os, "O_CLOEXEC"):
                parent_flags |= os.O_CLOEXEC
            if hasattr(os, "O_NOFOLLOW"):
                parent_flags |= os.O_NOFOLLOW
            parent_descriptor = os.open(parent, parent_flags)
            descriptor = os.open(temporary_name, flags, 0o600, dir_fd=parent_descriptor)
        else:
            descriptor = os.open(temporary, flags, 0o600)
        temporary_exists = True
        with os.fdopen(descriptor, "wb") as output:
            descriptor = None
            if os.name != "nt":
                os.fchmod(output.fileno(), 0o600)
            for chunk in chunks:
                if not chunk:
                    continue
                if not isinstance(chunk, (bytes, bytearray, memoryview)):
                    raise ValueError("upload chunks must be bytes")
                piece = bytes(chunk)
                written += len(piece)
                if written > int(max_bytes):
                    raise ValueError("media upload exceeds the maximum size")
                if len(header) < 512:
                    header.extend(piece[: 512 - len(header)])
                output.write(piece)
            if written == 0:
                raise ValueError("media upload is empty")
            if media_extension:
                validate_media_header(bytes(header), media_extension)
            output.flush()
            os.fsync(output.fileno())

        if parent_descriptor is not None:
            os.replace(
                temporary_name,
                target_name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
            temporary_exists = False
            try:
                os.fsync(parent_descriptor)
            except OSError:
                # The rename has already succeeded; some filesystems do not
                # support syncing directory descriptors.
                pass
        else:
            os.replace(temporary, target)
            temporary_exists = False
        return written
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_exists:
            try:
                if parent_descriptor is not None:
                    os.unlink(temporary_name, dir_fd=parent_descriptor)
                elif os.path.lexists(temporary):
                    os.remove(temporary)
            except (FileNotFoundError, OSError):
                pass
        if parent_descriptor is not None:
            os.close(parent_descriptor)


def atomic_write_bytes(
    abs_path: str,
    data: bytes,
    *,
    allowed_root: str,
    max_bytes: int,
    media_extension: Optional[str] = None,
) -> int:
    return atomic_write_chunks(
        abs_path,
        (bytes(data),),
        allowed_root=allowed_root,
        max_bytes=max_bytes,
        media_extension=media_extension,
    )
