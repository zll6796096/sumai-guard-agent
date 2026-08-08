from __future__ import annotations

from collections.abc import Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Barrier, Lock
from types import ModuleType
from typing import cast

import pytest

from app.errors import AppCheckInvalidError
from app.security.app_check import AppCheckVerifier, TokenVerifier, VerifiedAppCheck

APP_ROOT = Path(__file__).resolve().parents[1]
TEST_FILE = Path(__file__).resolve()
CONFIG_ENV_NAMES = (
    "APP_CHECK_REQUIRED",
    "FIREBASE_APP_ID",
    "MAX_UPLOAD_BYTES",
    "MAX_SOURCE_PIXELS",
)


def test_disabled_verification_accepts_missing_token_without_calling_verifier() -> None:
    def unexpected_verify(token: str) -> dict[str, object]:
        raise AssertionError(f"verifier must not be called: {token}")

    verifier = AppCheckVerifier(
        required=False,
        expected_app_id="1:123:ios:abc",
        token_verifier=unexpected_verify,
    )

    assert verifier.verify(None) is None


@pytest.mark.parametrize(
    "token",
    [None, "", "   \t"],
    ids=["missing", "empty", "whitespace"],
)
def test_required_verification_rejects_missing_or_blank_token(
    token: str | None,
) -> None:
    verifier = AppCheckVerifier(
        required=True,
        expected_app_id="1:123:ios:abc",
        token_verifier=lambda value: {"app_id": value},
    )

    with pytest.raises(AppCheckInvalidError):
        verifier.verify(token)


def test_exact_expected_app_id_returns_only_verified_app_id() -> None:
    verified_tokens: list[str] = []

    def valid_verify(token: str) -> dict[str, object]:
        assert token == "attested-token"
        verified_tokens.append(token)
        return {
            "app_id": "1:123:ios:abc",
            "sub": "private-install-claim",
        }

    verifier = AppCheckVerifier(
        required=True,
        expected_app_id="1:123:ios:abc",
        token_verifier=valid_verify,
    )

    result = verifier.verify("  attested-token  ")

    assert result == VerifiedAppCheck(app_id="1:123:ios:abc")
    assert vars(result) == {"app_id": "1:123:ios:abc"}
    assert not hasattr(result, "token")
    assert not hasattr(result, "sub")
    assert verified_tokens == ["attested-token"]


@pytest.mark.parametrize(
    "decoded",
    [{}, {"app_id": "1:123:ios:different"}],
    ids=["missing", "wrong"],
)
def test_required_verification_rejects_missing_or_wrong_app_id(
    decoded: dict[str, object],
) -> None:
    verifier = AppCheckVerifier(
        required=True,
        expected_app_id="1:123:ios:abc",
        token_verifier=lambda _: decoded,
    )

    with pytest.raises(AppCheckInvalidError):
        verifier.verify("attested-token")


@pytest.mark.parametrize(
    "decoded",
    [None, [], "not-claims", {"app_id": 123}, {"app_id": None}],
    ids=["none", "list", "string", "integer-app-id", "null-app-id"],
)
def test_required_verification_rejects_malformed_decoded_value(
    decoded: object,
) -> None:
    malformed_verify = cast(TokenVerifier, lambda _: decoded)
    verifier = AppCheckVerifier(
        required=True,
        expected_app_id="1:123:ios:abc",
        token_verifier=malformed_verify,
    )

    with pytest.raises(AppCheckInvalidError):
        verifier.verify("attested-token")


def test_non_ascii_app_id_becomes_fresh_sanitized_app_check_error() -> None:
    verifier = AppCheckVerifier(
        required=True,
        expected_app_id="1:123:ios:abc",
        token_verifier=lambda _: {
            "app_id": "1:123:ios:あ",
            "sub": "private-install-claim",
        },
    )

    with pytest.raises(AppCheckInvalidError) as caught:
        verifier.verify("attested-token-provider-private")

    assert caught.value.args == ()
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert vars(caught.value) == {}
    error_surface = " ".join(
        (str(caught.value), repr(caught.value), repr(vars(caught.value)))
    )
    assert "attested-token-provider-private" not in error_surface
    assert "private-install-claim" not in error_surface
    assert "1:123:ios:あ" not in error_surface


def test_claim_access_exception_becomes_fresh_sanitized_app_check_error() -> None:
    class SensitiveClaims(Mapping[str, object]):
        def __getitem__(self, key: str) -> object:
            raise KeyError(key)

        def __iter__(self) -> Iterator[str]:
            return iter(("app_id",))

        def __len__(self) -> int:
            return 1

        def get(self, key: str, default: object = None) -> object:
            assert key == "app_id"
            raise RuntimeError("sensitive-claim-access-sentinel")

    verifier = AppCheckVerifier(
        required=True,
        expected_app_id="1:123:ios:abc",
        token_verifier=lambda _: SensitiveClaims(),
    )

    with pytest.raises(AppCheckInvalidError) as caught:
        verifier.verify("sensitive-token-sentinel")

    assert caught.value.args == ()
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert vars(caught.value) == {}
    error_surface = " ".join(
        (str(caught.value), repr(caught.value), repr(vars(caught.value)))
    )
    assert "sensitive-claim-access-sentinel" not in error_surface
    assert "sensitive-token-sentinel" not in error_surface


def test_provider_exception_becomes_fresh_sanitized_app_check_error() -> None:
    provider_error = RuntimeError(
        "provider rejected attested-token with sub private-install-claim"
    )

    def failing_verify(_: str) -> dict[str, object]:
        raise provider_error

    verifier = AppCheckVerifier(
        required=True,
        expected_app_id="1:123:ios:abc",
        token_verifier=failing_verify,
    )

    with pytest.raises(AppCheckInvalidError) as caught:
        verifier.verify("attested-token")

    assert caught.value is not provider_error
    assert caught.value.args == ()
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert vars(caught.value) == {}


def test_default_verifier_uses_firebase_and_initializes_default_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    resolved_app = object()
    fake_firebase = ModuleType("firebase_admin")
    fake_app_check = ModuleType("firebase_admin.app_check")

    def get_app() -> None:
        calls.append("get_app")
        raise ValueError

    def initialize_app() -> object:
        calls.append("initialize_app")
        return resolved_app

    def verify_token(token: str, *, app: object) -> dict[str, object]:
        assert app is resolved_app
        calls.append(f"verify_token:{token}")
        return {"app_id": "1:123:ios:abc"}

    monkeypatch.setattr(fake_firebase, "get_app", get_app, raising=False)
    monkeypatch.setattr(fake_firebase, "initialize_app", initialize_app, raising=False)
    monkeypatch.setattr(fake_firebase, "app_check", fake_app_check, raising=False)
    monkeypatch.setattr(fake_app_check, "verify_token", verify_token, raising=False)
    monkeypatch.setitem(sys.modules, "firebase_admin", fake_firebase)
    monkeypatch.setitem(sys.modules, "firebase_admin.app_check", fake_app_check)

    verifier = AppCheckVerifier(
        required=True,
        expected_app_id="1:123:ios:abc",
    )

    assert verifier.verify("attested-token") == VerifiedAppCheck(
        app_id="1:123:ios:abc"
    )
    assert calls == [
        "get_app",
        "initialize_app",
        "verify_token:attested-token",
    ]


def test_default_verifier_handles_concurrent_first_initialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial_get_barrier = Barrier(2)
    initialize_barrier = Barrier(2)
    state_lock = Lock()
    resolved_app = object()
    initialized = False
    get_app_calls = 0
    verified: list[tuple[str, object | None]] = []
    fake_firebase = ModuleType("firebase_admin")
    fake_app_check = ModuleType("firebase_admin.app_check")

    def get_app() -> object:
        nonlocal get_app_calls
        with state_lock:
            get_app_calls += 1
            call_number = get_app_calls
        if call_number <= 2:
            initial_get_barrier.wait(timeout=5)
            raise ValueError("default app not initialized")
        with state_lock:
            assert initialized
        return resolved_app

    def initialize_app() -> object:
        nonlocal initialized
        initialize_barrier.wait(timeout=5)
        with state_lock:
            if initialized:
                raise ValueError("default app already initialized")
            initialized = True
        return resolved_app

    def verify_token(
        token: str,
        *,
        app: object | None = None,
    ) -> dict[str, object]:
        with state_lock:
            verified.append((token, app))
        return {"app_id": "1:123:ios:abc"}

    monkeypatch.setattr(fake_firebase, "get_app", get_app, raising=False)
    monkeypatch.setattr(fake_firebase, "initialize_app", initialize_app, raising=False)
    monkeypatch.setattr(fake_firebase, "app_check", fake_app_check, raising=False)
    monkeypatch.setattr(fake_app_check, "verify_token", verify_token, raising=False)
    monkeypatch.setitem(sys.modules, "firebase_admin", fake_firebase)
    monkeypatch.setitem(sys.modules, "firebase_admin.app_check", fake_app_check)

    verifier = AppCheckVerifier(
        required=True,
        expected_app_id="1:123:ios:abc",
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(verifier.verify, ["attested-token-1", "attested-token-2"])
        )

    assert results == [
        VerifiedAppCheck(app_id="1:123:ios:abc"),
        VerifiedAppCheck(app_id="1:123:ios:abc"),
    ]
    assert sorted(token for token, _ in verified) == [
        "attested-token-1",
        "attested-token-2",
    ]
    assert all(app is resolved_app for _, app in verified)


def test_default_verifier_import_and_disabled_construction_are_lazy() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(APP_ROOT)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import builtins; "
                "original_import = builtins.__import__; "
                "builtins.__import__ = lambda name, *args, **kwargs: "
                "(_ for _ in ()).throw(AssertionError('firebase import')) "
                "if name == 'firebase_admin' or name.startswith('firebase_admin.') "
                "else original_import(name, *args, **kwargs); "
                "from app.security.app_check import AppCheckVerifier; "
                "verifier = AppCheckVerifier(required=False, expected_app_id=''); "
                "assert verifier.verify(None) is None"
            ),
        ],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def _run_isolated_config(
    *,
    config_env: dict[str, str] | None = None,
    settings_kwargs: dict[str, object] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for name in CONFIG_ENV_NAMES:
        env.pop(name, None)
    env["PYTHON_DOTENV_DISABLED"] = "1"
    env["PYTHONPATH"] = str(APP_ROOT)
    env.update(config_env or {})
    env["SUMAI_TEST_SETTINGS_KWARGS"] = json.dumps(settings_kwargs or {})
    return subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json, os; "
                "kwargs = json.loads(os.environ.pop('SUMAI_TEST_SETTINGS_KWARGS')); "
                "from app.config import Settings; "
                "value = Settings(**kwargs); "
                "print(json.dumps({"
                "'app_check_required': value.app_check_required, "
                "'firebase_app_id': value.firebase_app_id, "
                "'max_upload_bytes': value.max_upload_bytes, "
                "'max_source_pixels': value.max_source_pixels, "
                "'version': value.version"
                "}))"
            ),
        ],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )


def test_module_collects_under_hostile_outer_app_check_config() -> None:
    env = os.environ.copy()
    env["APP_CHECK_REQUIRED"] = "definitely-not-true"
    env["PYTHON_DOTENV_DISABLED"] = "1"
    env["PYTHONPATH"] = str(APP_ROOT)

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", str(TEST_FILE)],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    assert result.returncode == 0, result.stderr


@pytest.fixture
def local_defaults_with_configured_outer_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    monkeypatch.setenv("APP_CHECK_REQUIRED", "true")
    monkeypatch.setenv("FIREBASE_APP_ID", "outer-firebase-app")
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "99")
    monkeypatch.setenv("MAX_SOURCE_PIXELS", "101")

    result = _run_isolated_config()

    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_app_check_is_optional_for_local_defaults(
    local_defaults_with_configured_outer_environment: dict[str, object],
) -> None:
    assert (
        local_defaults_with_configured_outer_environment["app_check_required"] is False
    )


def test_upload_limit_defaults_to_ten_mebibytes(
    local_defaults_with_configured_outer_environment: dict[str, object],
) -> None:
    assert local_defaults_with_configured_outer_environment["max_upload_bytes"] == (
        10 * 1024 * 1024
    )


def test_source_pixel_limit_defaults_to_twenty_five_million(
    local_defaults_with_configured_outer_environment: dict[str, object],
) -> None:
    assert (
        local_defaults_with_configured_outer_environment["max_source_pixels"]
        == 25_000_000
    )


def test_version_defaults_to_zero_point_three(
    local_defaults_with_configured_outer_environment: dict[str, object],
) -> None:
    assert local_defaults_with_configured_outer_environment["version"] == "0.3.0"


@pytest.mark.parametrize("raw_value", ["tru", "definitely-not-true"])
def test_malformed_app_check_flag_fails_closed_without_echoing_value(raw_value: str) -> None:
    result = _run_isolated_config(config_env={"APP_CHECK_REQUIRED": raw_value})

    assert result.returncode != 0
    assert "APP_CHECK_REQUIRED" in result.stderr
    assert raw_value not in result.stderr


@pytest.mark.parametrize("raw_value", ["", "   \t"], ids=["empty", "whitespace"])
def test_present_but_blank_app_check_flag_fails_closed(raw_value: str) -> None:
    result = _run_isolated_config(config_env={"APP_CHECK_REQUIRED": raw_value})

    assert result.returncode != 0
    assert result.stderr.rstrip().endswith("ValueError: APP_CHECK_REQUIRED")


@pytest.mark.parametrize("raw_value", ["1", " true ", "YES", "On"])
def test_app_check_accepts_strict_true_tokens(raw_value: str) -> None:
    result = _run_isolated_config(
        config_env={
            "APP_CHECK_REQUIRED": raw_value,
            "FIREBASE_APP_ID": "firebase-test-app",
        }
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["app_check_required"] is True


@pytest.mark.parametrize("raw_value", ["0", " false ", "NO", "Off"])
def test_app_check_accepts_strict_false_tokens(raw_value: str) -> None:
    result = _run_isolated_config(config_env={"APP_CHECK_REQUIRED": raw_value})

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["app_check_required"] is False


def test_required_app_check_rejects_blank_firebase_app_id() -> None:
    result = _run_isolated_config(
        settings_kwargs={"app_check_required": True, "firebase_app_id": ""}
    )

    assert result.returncode != 0
    assert result.stderr.rstrip().endswith("ValueError: firebase_app_id")


def test_required_app_check_rejects_whitespace_firebase_app_id() -> None:
    result = _run_isolated_config(
        settings_kwargs={"app_check_required": True, "firebase_app_id": "   \t"}
    )

    assert result.returncode != 0
    assert result.stderr.rstrip().endswith("ValueError: firebase_app_id")


def test_disabled_app_check_accepts_blank_firebase_app_id() -> None:
    result = _run_isolated_config(
        settings_kwargs={"app_check_required": False, "firebase_app_id": ""}
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["firebase_app_id"] == ""


@pytest.mark.parametrize("field_name", ["max_upload_bytes", "max_source_pixels"])
@pytest.mark.parametrize("invalid_value", [0, -1])
def test_image_limits_must_be_positive(field_name: str, invalid_value: int) -> None:
    result = _run_isolated_config(settings_kwargs={field_name: invalid_value})

    assert result.returncode != 0
    assert result.stderr.rstrip().endswith(f"ValueError: {field_name}")


@pytest.mark.parametrize("field_name", ["max_upload_bytes", "max_source_pixels"])
def test_image_limits_accept_one(field_name: str) -> None:
    result = _run_isolated_config(settings_kwargs={field_name: 1})

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)[field_name] == 1
