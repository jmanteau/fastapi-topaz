"""
Tests for testing utilities.

The testing module provides MockTopazConfig and rule builders for testing
authorization without a running Topaz instance. Supports both policy-based
and ReBAC rule matching with wildcards.

Test organization:
- TestMockTopazConfig: Core mock behavior (default decisions, recording)
- TestPolicyRules: Policy path rule matching with wildcards
- TestRelationRules: ReBAC relation rule matching
- TestInstallMock: Patching real TopazConfig with mocks
- TestMockTopazConfigAdvanced: Advanced recording and ReBAC detection
- TestPolicyRuleAdvanced: Deny rules and user filtering
- TestRelationRuleAdvanced: Deny relations and predicate-based rules
"""
from __future__ import annotations

from unittest.mock import Mock

import pytest

from fastapi_topaz.testing import (
    MockTopazConfig,
    install_mock,
    when_policy,
    when_relation,
)


class TestMockTopazConfig:
    """
    Core MockTopazConfig behavior.

    MockTopazConfig simulates authorization decisions without calling Topaz.
    Supports default allow/deny, rule-based matching, and decision recording.
    """

    @pytest.mark.asyncio
    async def test_default_allow(self):
        mock = MockTopazConfig(default_decision=True)
        result = await mock.check_decision(Mock(), "any.policy", "allowed", {})
        assert result is True

    @pytest.mark.asyncio
    async def test_default_deny(self):
        mock = MockTopazConfig(default_decision=False)
        result = await mock.check_decision(Mock(), "any.policy", "allowed", {})
        assert result is False

    @pytest.mark.asyncio
    async def test_records_decisions(self):
        mock = MockTopazConfig(default_decision=True, record_decisions=True)
        await mock.check_decision(Mock(), "test.policy", "allowed", {"key": "val"})

        assert len(mock.decisions) == 1
        assert mock.decisions[0].policy_path == "test.policy"
        assert mock.decisions[0].allowed is True

    @pytest.mark.asyncio
    async def test_find_decisions(self):
        mock = MockTopazConfig(default_decision=True, record_decisions=True)
        await mock.check_decision(Mock(), "policy.a", "allowed", {})
        await mock.check_decision(Mock(), "policy.b", "allowed", {})

        found = mock.find_decisions(policy_path="policy.a")
        assert len(found) == 1


class TestPolicyRules:
    """
    Policy path rule matching with wildcards.

    when_policy() creates rules that match policy paths. Supports glob-style
    wildcards (e.g., "myapp.GET.*" matches "myapp.GET.anything").
    """

    @pytest.mark.asyncio
    async def test_exact_match_allow(self):
        mock = MockTopazConfig(
            default_decision=False,
            rules=[when_policy("myapp.GET.documents").allow()],
        )
        result = await mock.check_decision(Mock(), "myapp.GET.documents", "allowed", {})
        assert result is True

    @pytest.mark.asyncio
    async def test_wildcard_match(self):
        mock = MockTopazConfig(
            default_decision=False,
            rules=[when_policy("myapp.GET.*").allow()],
        )
        result = await mock.check_decision(Mock(), "myapp.GET.anything", "allowed", {})
        assert result is True

    @pytest.mark.asyncio
    async def test_allow_for_users(self):
        mock = MockTopazConfig(
            default_decision=False,
            identity_returns="admin",
            rules=[when_policy("admin.policy").allow_for_users(["admin"])],
        )
        result = await mock.check_decision(Mock(), "admin.policy", "allowed", {})
        assert result is True

    @pytest.mark.asyncio
    async def test_allow_when_predicate(self):
        mock = MockTopazConfig(
            default_decision=False,
            rules=[when_policy("test").allow_when(lambda ctx: ctx.get("id") == "123")],
        )
        result = await mock.check_decision(Mock(), "test", "allowed", {"id": "123"})
        assert result is True

        result = await mock.check_decision(Mock(), "test", "allowed", {"id": "456"})
        assert result is False


class TestRelationRules:
    """
    ReBAC relation rule matching.

    when_relation() creates rules that match object_type and relation combinations.
    Supports wildcards (e.g., "document", "*" matches any relation on documents).
    """

    @pytest.mark.asyncio
    async def test_relation_allow(self):
        mock = MockTopazConfig(
            default_decision=False,
            rules=[when_relation("document", "can_read").allow()],
        )
        ctx = {"object_type": "document", "relation": "can_read", "object_id": "1"}
        result = await mock.check_decision(Mock(), "test.check", "allowed", ctx)
        assert result is True

    @pytest.mark.asyncio
    async def test_relation_for_object(self):
        mock = MockTopazConfig(
            default_decision=False,
            rules=[when_relation("document", "can_write").allow_for_object("doc-123")],
        )
        ctx = {"object_type": "document", "relation": "can_write", "object_id": "doc-123"}
        result = await mock.check_decision(Mock(), "test.check", "allowed", ctx)
        assert result is True

        ctx["object_id"] = "doc-456"
        result = await mock.check_decision(Mock(), "test.check", "allowed", ctx)
        assert result is False

    @pytest.mark.asyncio
    async def test_wildcard_relation(self):
        mock = MockTopazConfig(
            default_decision=False,
            rules=[when_relation("document", "*").allow()],
        )
        ctx = {"object_type": "document", "relation": "any_relation", "object_id": "1"}
        result = await mock.check_decision(Mock(), "test.check", "allowed", ctx)
        assert result is True


class TestInstallMock:
    """install_mock patches a real TopazConfig to use MockTopazConfig behavior."""

    @pytest.mark.asyncio
    async def test_patches_check_decision(self):
        class FakeConfig:
            async def check_decision(self, req, path, dec, ctx):
                return False

        target = FakeConfig()
        mock = MockTopazConfig(default_decision=True)

        # Create a simple monkeypatch-like object
        class FakeMonkeypatch:
            def setattr(self, obj, name, value):
                setattr(obj, name, value)

        install_mock(FakeMonkeypatch(), mock, target)

        result = await target.check_decision(Mock(), "test", "allowed", {})
        assert result is True


class TestMockTopazConfigAdvanced:
    """Advanced MockTopazConfig features: clearing decisions, ReBAC detection."""

    @pytest.mark.asyncio
    async def test_clear_decisions(self):
        mock = MockTopazConfig(default_decision=True, record_decisions=True)
        await mock.check_decision(Mock(), "policy.a", "allowed", {})
        assert len(mock.decisions) == 1

        mock.clear_decisions()
        assert len(mock.decisions) == 0

    @pytest.mark.asyncio
    async def test_unauthenticated_identity(self):
        mock = MockTopazConfig(
            default_decision=False,
            identity_returns=None,
            record_decisions=True,
        )
        await mock.check_decision(Mock(), "policy", "allowed", {})
        assert mock.decisions[0].identity_value is None

    @pytest.mark.asyncio
    async def test_rebac_check_recording(self):
        mock = MockTopazConfig(default_decision=True, record_decisions=True)
        ctx = {
            "object_type": "document",
            "object_id": "doc-123",
            "relation": "can_read",
        }
        await mock.check_decision(Mock(), "app.check", "allowed", ctx)

        assert mock.decisions[0].check_type == "rebac"
        assert mock.decisions[0].object_type == "document"
        assert mock.decisions[0].object_id == "doc-123"
        assert mock.decisions[0].relation == "can_read"


class TestPolicyRuleAdvanced:
    """Advanced policy rules: deny rules, user-specific permissions."""

    @pytest.mark.asyncio
    async def test_deny_rule(self):
        mock = MockTopazConfig(
            default_decision=True,
            rules=[when_policy("secret.*").deny()],
        )
        result = await mock.check_decision(Mock(), "secret.data", "allowed", {})
        assert result is False

    @pytest.mark.asyncio
    async def test_user_not_in_list(self):
        mock = MockTopazConfig(
            default_decision=False,
            identity_returns="regular-user",
            rules=[when_policy("admin.*").allow_for_users(["admin"])],
        )
        result = await mock.check_decision(Mock(), "admin.action", "allowed", {})
        assert result is False  # Falls back to default


class TestRelationRuleAdvanced:
    """Advanced relation rules: deny relations, user-specific, predicate-based."""

    @pytest.mark.asyncio
    async def test_deny_relation(self):
        mock = MockTopazConfig(
            default_decision=True,
            rules=[when_relation("document", "can_delete").deny()],
        )
        ctx = {"object_type": "document", "relation": "can_delete", "object_id": "1"}
        result = await mock.check_decision(Mock(), "app.check", "allowed", ctx)
        assert result is False

    @pytest.mark.asyncio
    async def test_allow_for_specific_users(self):
        mock = MockTopazConfig(
            default_decision=False,
            identity_returns="admin",
            rules=[when_relation("*", "can_delete").allow_for_users(["admin"])],
        )
        ctx = {"object_type": "document", "relation": "can_delete", "object_id": "1"}
        result = await mock.check_decision(Mock(), "app.check", "allowed", ctx)
        assert result is True

    @pytest.mark.asyncio
    async def test_predicate_with_context(self):
        def is_owner(ctx):
            return ctx.get("owner_id") == "user-1"

        mock = MockTopazConfig(
            default_decision=False,
            rules=[when_relation("document", "can_write").allow_when(is_owner)],
        )
        ctx = {
            "object_type": "document",
            "relation": "can_write",
            "object_id": "1",
            "owner_id": "user-1",
        }
        result = await mock.check_decision(Mock(), "app.check", "allowed", ctx)
        assert result is True


class TestRulePrecedence:
    """Rule precedence: first matching rule wins."""

    @pytest.mark.asyncio
    async def test_first_matching_rule_wins(self):
        """First matching rule should take precedence over later rules."""
        mock = MockTopazConfig(
            default_decision=True,
            rules=[
                when_policy("myapp.GET.secret").deny(),  # More specific, listed first
                when_policy("myapp.GET.*").allow(),  # Less specific, listed second
            ],
        )
        # First rule matches and denies
        result = await mock.check_decision(Mock(), "myapp.GET.secret", "allowed", {})
        assert result is False

        # Second rule matches other paths
        result = await mock.check_decision(Mock(), "myapp.GET.public", "allowed", {})
        assert result is True

    @pytest.mark.asyncio
    async def test_order_matters_for_overlapping_rules(self):
        """Demonstrate that rule order determines which rule applies."""
        # Deny-first configuration
        mock_deny_first = MockTopazConfig(
            default_decision=False,
            rules=[
                when_policy("app.*").deny(),
                when_policy("app.public").allow(),
            ],
        )
        # Deny rule matches first, so public is denied
        result = await mock_deny_first.check_decision(Mock(), "app.public", "allowed", {})
        assert result is False

        # Allow-first configuration
        mock_allow_first = MockTopazConfig(
            default_decision=False,
            rules=[
                when_policy("app.public").allow(),
                when_policy("app.*").deny(),
            ],
        )
        # Allow rule matches first, so public is allowed
        result = await mock_allow_first.check_decision(Mock(), "app.public", "allowed", {})
        assert result is True
