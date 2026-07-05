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
