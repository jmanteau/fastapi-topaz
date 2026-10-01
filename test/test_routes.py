"""Tests for route helpers that bridge FastAPI versions."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from fastapi_topaz._routes import set_route_attr


class TestSetRouteAttr:
    def test_warns_on_unknown_route_context_layout(self, caplog):
        original = SimpleNamespace(openapi_extra=None)
        # A route context exposing original_route but not the private _route_context
        context = SimpleNamespace(original_route=original)

        with caplog.at_level(logging.WARNING, logger="fastapi_topaz.routes"):
            set_route_attr(context, "openapi_extra", {"x": 1})

        assert original.openapi_extra == {"x": 1}
        assert "Unsupported FastAPI route context layout" in caplog.text

    def test_plain_route_set_without_warning(self, caplog):
        route = SimpleNamespace(openapi_extra=None)

        with caplog.at_level(logging.WARNING, logger="fastapi_topaz.routes"):
            set_route_attr(route, "openapi_extra", {"x": 1})

        assert route.openapi_extra == {"x": 1}
        assert caplog.text == ""
