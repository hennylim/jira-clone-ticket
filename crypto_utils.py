import os
import base64
import json
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.fernet import Fernet

def derive_key(password: str, salt: bytes) -> bytes:
    """Derive a 32-byte key from a password and salt using PBKDF2."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480000,
    )
    # Fernet key must be 32 url-safe base64-encoded bytes
    return base64.urlsafe_b64encode(kdf.derive(password.encode()))

def encrypt_with_key(key: bytes, data_dict: dict) -> str:
    """Encrypt a dictionary using a pre-derived Fernet key."""
    f = Fernet(key)
    json_data = json.dumps(data_dict).encode()
    return f.encrypt(json_data).decode()

def decrypt_with_key(key: bytes, encrypted_data: str) -> dict:
    """Decrypt data using a pre-derived Fernet key."""
    f = Fernet(key)
    decrypted_data = f.decrypt(encrypted_data.encode())
    return json.loads(decrypted_data.decode())

def encrypt_data(password: str, salt_b64: str, data_dict: dict) -> str:
    """Encrypt a dictionary using a key derived from the password and b64 salt."""
    salt = base64.b64decode(salt_b64)
    key = derive_key(password, salt)
    return encrypt_with_key(key, data_dict)

#def decrypt_data(password_or_key: str | bytes, salt_b64_or_encrypted: str, encrypted_data: Optional[str] = None) -> dict:
def decrypt_data(password_or_key: str | bytes, salt_b64_or_encrypted: str, encrypted_data: str | None = None) -> dict:
    """
    Experimental polymorphic decrypt. 
    If 3 args are passed: (password, salt_b64, encrypted_data)
    If 2 args are passed: (derived_key, encrypted_data)
    """
    if encrypted_data is not None:
        # (password, salt_b64, encrypted_data)
        password = password_or_key
        salt_b64 = salt_b64_or_encrypted
        salt = base64.b64decode(salt_b64)
        key = derive_key(password, salt)
        return decrypt_with_key(key, encrypted_data)
    else:
        # (derived_key, encrypted_data)
        key = password_or_key
        return decrypt_with_key(key, salt_b64_or_encrypted)

def generate_salt() -> str:
    """Generate a new random salt as a base64 string."""
    return base64.b64encode(os.urandom(16)).decode()
