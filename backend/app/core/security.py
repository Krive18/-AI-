import secrets
import string

from argon2 import PasswordHasher, Type, extract_parameters
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)
_TEMPORARY_PASSWORD_SYMBOLS = "!@#$%*-_+=?"
_TEMPORARY_PASSWORD_LENGTH = 20
_SYSTEM_RANDOM = secrets.SystemRandom()


class InvalidPasswordHashError(ValueError):
    """A persistence input is not an encoded Argon2id password hash."""


def normalize_login_name(value: str) -> str:
    return value.strip().casefold()


def is_strong_password(value: str) -> bool:
    return len(value) >= 12 and all(
        (
            any(character in string.ascii_lowercase for character in value),
            any(character in string.ascii_uppercase for character in value),
            any(character in string.digits for character in value),
            any(not character.isalnum() for character in value),
        )
    )


def hash_password(value: str) -> str:
    return _PASSWORD_HASHER.hash(value)


def verify_password(value: str, encoded: str) -> bool:
    try:
        return _PASSWORD_HASHER.verify(encoded, value)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def validate_password_hash(encoded: str) -> None:
    try:
        parameters = extract_parameters(encoded)
    except InvalidHashError:
        raise InvalidPasswordHashError("password hash is invalid") from None
    if parameters.type is not Type.ID:
        raise InvalidPasswordHashError("password hash is invalid")


def generate_temporary_password() -> str:
    required = [
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.digits),
        secrets.choice(_TEMPORARY_PASSWORD_SYMBOLS),
    ]
    alphabet = (
        string.ascii_lowercase
        + string.ascii_uppercase
        + string.digits
        + _TEMPORARY_PASSWORD_SYMBOLS
    )
    required.extend(
        secrets.choice(alphabet)
        for _ in range(_TEMPORARY_PASSWORD_LENGTH - len(required))
    )
    _SYSTEM_RANDOM.shuffle(required)
    return "".join(required)
