import re

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


_HEX_PATTERN = re.compile(r"^[0-9a-fA-F]+$")
_SM4_BLOCK_HEX_LENGTH = 32
_MAX_SM4_CIPHER_HEX_LENGTH = 512
_MAX_SM4_PLAIN_BYTES = 240


def _sm4_key_bytes(secret_key_hex: str) -> bytes:
    key_hex = str(secret_key_hex or "").strip()
    if len(key_hex) != 32 or not _HEX_PATTERN.fullmatch(key_hex):
        raise ValueError("SM4 key must be 32 hex chars")
    return bytes.fromhex(key_hex)


def extract_bearer_token(authorization) -> str:
    text = str(authorization or "").strip()
    if not text.lower().startswith("bearer "):
        return ""
    return text[7:].strip()


def sm4_encrypt_ecb_pkcs7(plain_text: str, secret_key_hex: str) -> str:
    key_bytes = _sm4_key_bytes(secret_key_hex)
    plain_bytes = str(plain_text or "").encode("utf-8")
    if len(plain_bytes) > _MAX_SM4_PLAIN_BYTES:
        raise ValueError("SM4 plain text is too long")
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plain_bytes) + padder.finalize()
    # Compatibility boundary: the existing collector protocol mandates SM4-ECB.
    # It is restricted to this short, timestamped bearer payload and must be
    # transported over TLS; it is not a general-purpose encryption primitive.
    encryptor = Cipher(algorithms.SM4(key_bytes), modes.ECB()).encryptor()
    encrypted = encryptor.update(padded) + encryptor.finalize()
    return encrypted.hex()


def sm4_decrypt_ecb_pkcs7(cipher_text_hex: str, secret_key_hex: str) -> str:
    cipher_hex = str(cipher_text_hex or "").strip()
    if (
        len(cipher_hex) == 0
        or len(cipher_hex) > _MAX_SM4_CIPHER_HEX_LENGTH
        or len(cipher_hex) % _SM4_BLOCK_HEX_LENGTH != 0
        or not _HEX_PATTERN.fullmatch(cipher_hex)
    ):
        raise ValueError("SM4 cipher text must be bounded block-aligned hex")

    key_bytes = _sm4_key_bytes(secret_key_hex)
    cipher_bytes = bytes.fromhex(cipher_hex)
    # See the encryption-side compatibility note above. Freshness and replay
    # rejection are enforced by the digital-human service after decryption.
    decryptor = Cipher(algorithms.SM4(key_bytes), modes.ECB()).decryptor()
    padded = decryptor.update(cipher_bytes) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    plain_bytes = unpadder.update(padded) + unpadder.finalize()
    if len(plain_bytes) > _MAX_SM4_PLAIN_BYTES:
        raise ValueError("SM4 plain text is too long")
    return plain_bytes.decode("utf-8")
