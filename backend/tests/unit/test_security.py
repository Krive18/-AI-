import string

import pytest
from argon2 import PasswordHasher, Type

from app.core.security import (
    InvalidPasswordHashError,
    generate_temporary_password,
    hash_password,
    normalize_login_name,
    validate_password_hash,
    verify_password,
)


def test_login_name_is_trimmed_and_casefolded() -> None:
    assert normalize_login_name("  Alice.OP  ") == "alice.op"
    assert normalize_login_name("  STRASSEẞ  ") == "strassess"


def test_argon2id_hash_uses_required_parameters_and_verifies_password() -> None:
    encoded = hash_password("Correct-Horse-9!")

    assert encoded.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    assert encoded != "Correct-Horse-9!"
    assert verify_password("Correct-Horse-9!", encoded)
    assert not verify_password("wrong-password", encoded)
    assert not verify_password("Correct-Horse-9!", "not-an-argon2-hash")


def test_temporary_password_is_random_and_uses_conservative_required_classes() -> None:
    values = {generate_temporary_password() for _ in range(16)}
    allowed = set(string.ascii_letters + string.digits + "!@#$%*-_+=?")

    assert len(values) == 16
    for value in values:
        assert len(value) >= 20
        assert set(value) <= allowed
        assert any(ch.islower() for ch in value)
        assert any(ch.isupper() for ch in value)
        assert any(ch.isdigit() for ch in value)
        assert any(ch in "!@#$%*-_+=?" for ch in value)


def test_password_hash_validation_accepts_only_argon2id_without_leaking_value() -> None:
    validate_password_hash(hash_password("Correct-Horse-9!"))
    argon2i_hash = PasswordHasher(type=Type.I).hash("Correct-Horse-9!")

    for invalid_value in ("Plaintext-Password-9!", argon2i_hash):
        with pytest.raises(InvalidPasswordHashError) as invalid_hash:
            validate_password_hash(invalid_value)

        assert invalid_value not in str(invalid_hash.value)
