"""D5: deprecated names on fastapi_topaz are served lazily with a warning."""

import warnings

import pytest

import fastapi_topaz
from fastapi_topaz import _defaults


class TestLazyDeprecatedAttributes:
    def test_authorization_error_warns_and_resolves(self):
        with pytest.warns(DeprecationWarning, match="AuthorizationError is deprecated"):
            obj = getattr(fastapi_topaz, "AuthorizationError")
        assert obj is _defaults.AuthorizationError

    def test_type_alias_warns_and_resolves(self):
        with pytest.warns(DeprecationWarning, match="IdentityMapper is deprecated"):
            obj = getattr(fastapi_topaz, "IdentityMapper")
        assert obj is _defaults.IdentityMapper

    def test_unknown_attribute_raises(self):
        with pytest.raises(AttributeError, match="no attribute 'DoesNotExist'"):
            getattr(fastapi_topaz, "DoesNotExist")

    def test_plain_import_emits_no_warning(self):
        """Importing the package (without touching deprecated names) is silent."""
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            import importlib

            importlib.reload(fastapi_topaz)


class TestStarImport:
    def test_star_import_emits_no_warning(self):
        """Regression: deprecated names in __all__ made `import *` warn (or
        fail under -W error)."""
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            exec("from fastapi_topaz import *", {})

    def test_deprecated_names_still_reachable(self):
        with pytest.warns(DeprecationWarning):
            assert fastapi_topaz.StringMapper is _defaults.StringMapper


class TestAuthorizationErrorRaisable:
    def test_propagates_through_contextmanager(self):
        """Regression: a frozen dataclass exception raised FrozenInstanceError
        when contextlib assigned __traceback__ on re-raise."""
        from contextlib import contextmanager

        @contextmanager
        def ctx():
            yield

        with pytest.raises(_defaults.AuthorizationError) as exc:
            with ctx():
                raise _defaults.AuthorizationError("inst", "app.GET.x")
        assert exc.value.policy_path == "app.GET.x"

    def test_is_hashable(self):
        err = _defaults.AuthorizationError("inst", "app.GET.x")
        assert {err: 1}[err] == 1
