"""PKCE и генерация идентификаторов сессий/состояний."""
import base64
import hashlib
import secrets


def generate_pkce() -> tuple[str, str]:
    """Возвращает (code_verifier, code_challenge) по методу S256.

    code_verifier — высокоэнтропийная случайная строка; code_challenge —
    base64url(SHA256(verifier)) без padding.
    """
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def new_session_id() -> str:
    return secrets.token_urlsafe(48)


def new_state() -> str:
    return secrets.token_urlsafe(32)
