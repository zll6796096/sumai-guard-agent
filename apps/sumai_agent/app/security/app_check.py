from __future__ import annotations

import hmac
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from app.errors import AppCheckInvalidError


DecodedToken = Mapping[str, object]
TokenVerifier = Callable[[str], DecodedToken]


def _verify_with_firebase(token: str) -> DecodedToken:
    import firebase_admin
    from firebase_admin import app_check

    try:
        resolved_app = firebase_admin.get_app()
    except ValueError:
        try:
            resolved_app = firebase_admin.initialize_app()
        except ValueError:
            resolved_app = firebase_admin.get_app()
    return app_check.verify_token(token, app=resolved_app)


@dataclass(frozen=True)
class VerifiedAppCheck:
    app_id: str


class AppCheckVerifier:
    def __init__(
        self,
        *,
        required: bool,
        expected_app_id: str,
        token_verifier: TokenVerifier | None = None,
    ) -> None:
        self._required = required
        self._expected_app_id = expected_app_id
        self._token_verifier = (
            token_verifier if token_verifier is not None else _verify_with_firebase
        )

    def verify(self, token: str | None) -> VerifiedAppCheck | None:
        if not self._required:
            return None
        if token is None or not token.strip():
            raise AppCheckInvalidError from None

        verified_app_id: str | None = None
        try:
            decoded: object = self._token_verifier(token.strip())
            if isinstance(decoded, Mapping):
                app_id = decoded.get("app_id")
                if isinstance(app_id, str) and hmac.compare_digest(
                    app_id,
                    self._expected_app_id,
                ):
                    verified_app_id = app_id
        except Exception:
            pass

        if verified_app_id is None:
            raise AppCheckInvalidError from None

        return VerifiedAppCheck(app_id=verified_app_id)
