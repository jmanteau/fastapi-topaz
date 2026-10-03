"""Public names of the fastapi_topaz package."""

import warnings

import pytest

import fastapi_topaz


class TestRemovedAliases:
    """The 1.x deprecated aliases were removed in 2.0."""

    @pytest.mark.parametrize(
        "name",
        ["AuthorizationError", "IdentityMapper", "StringMapper", "ObjectMapper", "ResourceMapper"],
    )
    def test_removed_alias_is_not_importable(self, name):
        with pytest.raises(ImportError):
            exec(f"from fastapi_topaz import {name}", {})

    def test_unknown_attribute_raises(self):
        with pytest.raises(AttributeError):
            getattr(fastapi_topaz, "DoesNotExist")


class TestStarImport:
    def test_star_import_emits_no_warning(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            exec("from fastapi_topaz import *", {})

    def test_all_names_resolve(self):
        for name in fastapi_topaz.__all__:
            assert hasattr(fastapi_topaz, name), name
