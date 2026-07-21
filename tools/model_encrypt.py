#!/usr/bin/env python3
"""
Beacon model encryption tool (v2 header + XOR payload).

This script generates a v2-encrypted model file that the Analyzer can decrypt via:
  Analyzer/Analyzer/Core/ModelEncryption.cpp

Format (little-endian):
  magic[8]        = b"BENCv2\\0\\0"
  version(u32)    = 2
  headerSize(u32) = total header bytes (including magic)
  encryptedAtMs(u64)
  trialSeconds(u32)
  customIdLen(u32)
  customId bytes (utf-8)
  [optional future padding/fields]
  payload bytes: XOR(plaintext, key) with key index reset at payload start

Examples:
  # Encrypt a TensorRT engine (output: *.engine.enc)
  python3 tools/model_encrypt.py --key k123 demo.engine

  # Encrypt OpenVINO IR (xml + bin) together
  python3 tools/model_encrypt.py --key k123 --openvino-pair demo.xml

  # Encrypt with trial duration and custom id
  python3 tools/model_encrypt.py --key k123 --trial-seconds 86400 --custom-id CID001 demo.onnx
"""

import argparse
import os
import struct
import time
from typing import Optional, Tuple


MAGIC = b"BENCv2\x00\x00"
VERSION = 2


def _normalize_suffix(value: str) -> str:
    """执行归一化`suffix`。"""
    sfx = str(value or "").strip()
    if not sfx:
        return ".enc"
    if sfx == "." or sfx == "..":
        return ".enc"
    if not sfx.startswith("."):
        sfx = "." + sfx
    if len(sfx) > 16:
        return ".enc"
    return sfx


def _looks_like_v2(abs_path: str) -> bool:
    """处理外观`like``v2`。"""
    try:
        with open(abs_path, "rb") as f:
            head = f.read(len(MAGIC))
        return head == MAGIC
    except Exception:
        return False


def _require_existing_file(src_abs: str) -> None:
    """处理需要现有文件。"""
    if not src_abs:
        raise SystemExit("src is empty")
    if not os.path.exists(src_abs):
        raise SystemExit(f"src not found: {src_abs}")


def _require_key_bytes(key: str) -> bytes:
    """返回需要键字节数。"""
    key_bytes = str(key or "").encode("utf-8")
    if not key_bytes:
        raise SystemExit("--key is required")
    return key_bytes


def _normalize_trial_seconds(trial_seconds: int) -> int:
    """执行归一化`trial`秒数。"""
    try:
        trial = int(trial_seconds or 0)
    except Exception:
        trial = 0
    return max(0, trial)


def _truncate_custom_id_bytes(custom_id: str) -> bytes:
    """返回`truncate``custom`ID字节数。"""
    cid_bytes = str(custom_id or "").encode("utf-8")
    return cid_bytes[:1024] if len(cid_bytes) > 1024 else cid_bytes


def _xor_encrypt_stream(src, dst, *, key_bytes: bytes, chunk_size: int) -> None:
    """处理`xor`加密流。"""
    idx = 0
    klen = len(key_bytes)
    while True:
        data = src.read(int(chunk_size))
        if not data:
            break
        buf = bytearray(data)
        for i in range(len(buf)):
            buf[i] ^= key_bytes[(idx + i) % klen]
        idx += len(buf)
        dst.write(buf)


def _encrypt_to_tmp(
    src_abs: str,
    tmp_abs: str,
    *,
    key_bytes: bytes,
    trial: int,
    cid_bytes: bytes,
    chunk_size: int,
) -> None:
    """处理加密`to``tmp`。"""
    encrypted_at_ms = int(time.time() * 1000)
    header_size = len(MAGIC) + 4 + 4 + 8 + 4 + 4 + len(cid_bytes)
    header_fixed = struct.pack(
        "<IIQII",
        int(VERSION),
        int(header_size),
        int(encrypted_at_ms),
        int(trial),
        int(len(cid_bytes)),
    )

    with open(src_abs, "rb") as src, open(tmp_abs, "wb") as dst:
        dst.write(MAGIC)
        dst.write(header_fixed)
        if cid_bytes:
            dst.write(cid_bytes)
        _xor_encrypt_stream(src, dst, key_bytes=key_bytes, chunk_size=chunk_size)
        dst.flush()


def encrypt_file_v2(
    src_abs: str,
    dst_abs: str,
    *,
    key: str,
    trial_seconds: int = 0,
    custom_id: str = "",
    overwrite: bool = False,
    chunk_size: int = 4 * 1024 * 1024,
) -> None:
    """处理加密文件`v2`。"""
    _require_existing_file(src_abs)
    key_bytes = _require_key_bytes(key)
    trial = _normalize_trial_seconds(trial_seconds)
    cid_bytes = _truncate_custom_id_bytes(custom_id)
    if os.path.exists(dst_abs) and not overwrite:
        raise SystemExit(f"dst exists (use --overwrite): {dst_abs}")

    tmp_abs = dst_abs + ".tmp"
    try:
        _encrypt_to_tmp(
            src_abs,
            tmp_abs,
            key_bytes=key_bytes,
            trial=trial,
            cid_bytes=cid_bytes,
            chunk_size=chunk_size,
        )
        os.replace(tmp_abs, dst_abs)
    finally:
        try:
            if os.path.exists(tmp_abs):
                os.remove(tmp_abs)
        except Exception:
            pass


def _derive_output(src_abs: str, *, out_abs: Optional[str], suffix: str) -> str:
    """处理`derive``output`。"""
    if out_abs:
        return out_abs
    return src_abs + suffix


def _encrypt_openvino_pair(
    xml_abs: str,
    *,
    out_abs: Optional[str],
    key: str,
    trial_seconds: int,
    custom_id: str,
    suffix: str,
    overwrite: bool,
    chunk_size: int,
) -> Tuple[str, str]:
    """处理加密`openvino``pair`。"""
    dst_xml = _derive_output(xml_abs, out_abs=out_abs, suffix=suffix)
    encrypt_file_v2(
        xml_abs,
        dst_xml,
        key=key,
        trial_seconds=trial_seconds,
        custom_id=custom_id,
        overwrite=overwrite,
        chunk_size=chunk_size,
    )

    bin_abs = os.path.splitext(xml_abs)[0] + ".bin"
    if not os.path.exists(bin_abs):
        raise SystemExit(f"OpenVINO .bin not found next to xml: {bin_abs}")
    dst_bin = bin_abs + suffix
    encrypt_file_v2(
        bin_abs,
        dst_bin,
        key=key,
        trial_seconds=trial_seconds,
        custom_id=custom_id,
        overwrite=overwrite,
        chunk_size=chunk_size,
    )

    return dst_xml, dst_bin


def main() -> None:
    """处理`main`。"""
    p = argparse.ArgumentParser(description="Beacon model encryption tool (v2 header + XOR payload)")
    p.add_argument("src", help="Input model path (e.g. demo.engine / demo.xml / demo.onnx)")
    p.add_argument("--out", dest="out_abs", default=None, help="Output path (default: <src> + suffix)")
    p.add_argument("--key", required=True, help="Encryption key (must match Analyzer config modelEncryptKey)")
    p.add_argument("--suffix", default=".enc", help="Encrypted suffix (default: .enc)")
    p.add_argument("--trial-seconds", type=int, default=0, help="Trial duration in seconds (0 = no expiry)")
    p.add_argument("--custom-id", default="", help="Custom ID to embed into the encrypted file")
    p.add_argument("--overwrite", action="store_true", help="Overwrite output if it already exists")
    p.add_argument("--openvino-pair", action="store_true", help="When src is .xml, also encrypt sibling .bin")
    p.add_argument("--chunk-size", type=int, default=4 * 1024 * 1024, help="Streaming chunk size in bytes")
    p.add_argument("--detect-only", action="store_true", help="Exit 0 if src looks v2-encrypted (magic), else exit 1")

    args = p.parse_args()

    src_abs = os.path.abspath(args.src)
    suffix = _normalize_suffix(args.suffix)

    if args.detect_only:
        raise SystemExit(0 if _looks_like_v2(src_abs) else 1)

    if args.openvino_pair or src_abs.lower().endswith(".xml"):
        if args.openvino_pair or src_abs.lower().endswith(".xml"):
            if args.openvino_pair:
                dst_xml, dst_bin = _encrypt_openvino_pair(
                    src_abs,
                    out_abs=args.out_abs,
                    key=args.key,
                    trial_seconds=args.trial_seconds,
                    custom_id=args.custom_id,
                    suffix=suffix,
                    overwrite=bool(args.overwrite),
                    chunk_size=int(args.chunk_size),
                )
                print(dst_xml)
                print(dst_bin)
                return

    dst_abs = _derive_output(src_abs, out_abs=args.out_abs, suffix=suffix)
    encrypt_file_v2(
        src_abs,
        dst_abs,
        key=args.key,
        trial_seconds=args.trial_seconds,
        custom_id=args.custom_id,
        overwrite=bool(args.overwrite),
        chunk_size=int(args.chunk_size),
    )
    print(dst_abs)


if __name__ == "__main__":
    main()
