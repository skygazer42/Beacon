import re

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


_HEX_PATTERN = re.compile(r"^[0-9a-fA-F]+$")


def extract_bearer_token(authorization) -> str:
    text = str(authorization or "").strip()
    if not text.lower().startswith("bearer "):
        return ""
    return text[7:].strip()


def sm4_encrypt_ecb_pkcs7(plain_text: str, secret_key_hex: str) -> str:
    key_bytes = bytes.fromhex(str(secret_key_hex or "").strip())
    plain_bytes = str(plain_text or "").encode("utf-8")
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plain_bytes) + padder.finalize()
    encryptor = Cipher(algorithms.SM4(key_bytes), modes.ECB()).encryptor()
    encrypted = encryptor.update(padded) + encryptor.finalize()
    return encrypted.hex()


def sm4_decrypt_ecb_pkcs7(cipher_text_hex: str, secret_key_hex: str) -> str:
    cipher_hex = str(cipher_text_hex or "").strip()
    key_hex = str(secret_key_hex or "").strip()
    if len(key_hex) != 32 or not _HEX_PATTERN.match(key_hex):
        raise ValueError("SM4 key must be 32 hex chars")
    if len(cipher_hex) == 0 or len(cipher_hex) % 2 != 0 or not _HEX_PATTERN.match(cipher_hex):
        raise ValueError("SM4 cipher text must be even-length hex")

    key_bytes = bytes.fromhex(key_hex)
    cipher_bytes = bytes.fromhex(cipher_hex)
    decryptor = Cipher(algorithms.SM4(key_bytes), modes.ECB()).decryptor()
    padded = decryptor.update(cipher_bytes) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    plain_bytes = unpadder.update(padded) + unpadder.finalize()
    return plain_bytes.decode("utf-8")
