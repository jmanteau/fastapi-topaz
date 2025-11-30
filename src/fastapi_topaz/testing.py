"""
Testing utilities for fastapi-topaz.

Provides MockTopazConfig and helpers to test authorization without a running Topaz instance.
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Any, Callable

from fastapi import Request

__all__ = [
    "MockTopazConfig",
    "when_policy",
    "when_relation",
    "install_mock",
    "Decision",
]


@dataclass
class Decision:
    """Recorded authorization decision for assertions."""

    policy_path: str
    decision_name: str
    allowed: bool
    identity_value: str | None = None
    resource_context: dict[str, Any] = field(default_factory=dict)
    check_type: str = "policy"  # "policy" or "rebac"
    object_type: str | None = None
    object_id: str | None = None
    relation: str | None = None


@dataclass
class PolicyRule:
    """Rule for matching policy checks."""

    pattern: str
    decision: bool | Callable[[dict[str, Any]], bool]
    users: list[str] | None = None

    def matches(self, policy_path: str, identity_value: str | None) -> bool:
        if not fnmatch.fnmatch(policy_path, self.pattern):
            return False
        if self.users and identity_value not in self.users:
            return False
        return True

    def get_decision(self, context: dict[str, Any]) -> bool:
        if callable(self.decision):
            return self.decision(context)
        return self.decision


@dataclass
class RelationRule:
    """Rule for matching ReBAC relation checks."""

    object_type: str
    relation: str
    decision: bool | Callable[[dict[str, Any]], bool]
    users: list[str] | None = None
    object_ids: list[str] | None = None

    def matches(
        self, obj_type: str, rel: str, obj_id: str | None, identity: str | None
    ) -> bool:
        if not fnmatch.fnmatch(obj_type, self.object_type):
            return False
        if not fnmatch.fnmatch(rel, self.relation):
            return False
        if self.users and identity not in self.users:
            return False
        if self.object_ids and obj_id not in self.object_ids:
            return False
        return True

    def get_decision(self, context: dict[str, Any]) -> bool:
        if callable(self.decision):
            return self.decision(context)
        return self.decision


class PolicyRuleBuilder:
    """Builder for creating policy rules."""

    def __init__(self, pattern: str):
        self.pattern = pattern

    def allow(self) -> PolicyRule:
        return PolicyRule(self.pattern, True)

    def deny(self) -> PolicyRule:
        return PolicyRule(self.pattern, False)

    def allow_when(self, predicate: Callable[[dict[str, Any]], bool]) -> PolicyRule:
        return PolicyRule(self.pattern, predicate)

    def allow_for_users(self, users: list[str]) -> PolicyRule:
        return PolicyRule(self.pattern, True, users=users)


class RelationRuleBuilder:
    """Builder for creating relation rules."""

    def __init__(self, object_type: str, relation: str):
        self.object_type = object_type
        self.relation = relation

    def allow(self) -> RelationRule:
        return RelationRule(self.object_type, self.relation, True)

    def deny(self) -> RelationRule:
        return RelationRule(self.object_type, self.relation, False)

    def allow_for_object(self, object_id: str) -> RelationRule:
        return RelationRule(self.object_type, self.relation, True, object_ids=[object_id])

    def allow_for_users(self, users: list[str]) -> RelationRule:
        return RelationRule(self.object_type, self.relation, True, users=users)

    def allow_when(self, predicate: Callable[[dict[str, Any]], bool]) -> RelationRule:
        return RelationRule(self.object_type, self.relation, predicate)


def when_policy(pattern: str) -> PolicyRuleBuilder:
    """Create a policy rule builder. Supports wildcards (e.g., 'myapp.GET.*')."""
    return PolicyRuleBuilder(pattern)


def when_relation(object_type: str, relation: str) -> RelationRuleBuilder:
    """Create a relation rule builder. Supports wildcards (e.g., 'document', '*')."""
    return RelationRuleBuilder(object_type, relation)


class MockTopazConfig:
    """
    Mock TopazConfig for testing without a running Topaz instance.

    Args:
        default_decision: Default allow/deny when no rules match
        rules: List of PolicyRule or RelationRule for granular control
        record_decisions: Whether to record decisions for assertions
        identity_returns: Simulated identity value (or None for unauthenticated)
    """

    def __init__(
        self,
        default_decision: bool = True,
        rules: list[PolicyRule | RelationRule] | None = None,
        record_decisions: bool = False,
        identity_returns: str | None = "mock-user",
    ):
        self.default_decision = default_decision
        self.rules = rules or []
        self.record_decisions = record_decisions
        self.identity_returns = identity_returns
        self.decisions: list[Decision] = []
        self.policy_path_root = "mock"

    def _find_policy_decision(
        self, policy_path: str, identity_value: str | None, context: dict[str, Any]
    ) -> bool:
        for rule in self.rules:
            if isinstance(rule, PolicyRule) and rule.matches(policy_path, identity_value):
                return rule.get_decision(context)
        return self.default_decision

    def _find_relation_decision(
        self,
        obj_type: str,
        relation: str,
        obj_id: str | None,
        identity: str | None,
        context: dict[str, Any],
    ) -> bool:
        for rule in self.rules:
            if isinstance(rule, RelationRule) and rule.matches(
                obj_type, relation, obj_id, identity
            ):
                return rule.get_decision(context)
        return self.default_decision

    async def check_decision(
        self,
        request: Request,
        policy_path: str,
        decision: str,
        resource_context: dict[str, Any] | None = None,
    ) -> bool:
        ctx = dict(resource_context) if resource_context else {}
        identity = self.identity_returns

        # Check if this is a ReBAC check
        if ctx.get("object_type") and ctx.get("relation"):
            result = self._find_relation_decision(
                ctx["object_type"],
                ctx["relation"],
                ctx.get("object_id"),
                identity,
                ctx,
            )
            if self.record_decisions:
                self.decisions.append(
                    Decision(
                        policy_path=policy_path,
                        decision_name=decision,
                        allowed=result,
                        identity_value=identity,
                        resource_context=ctx,
                        check_type="rebac",
                        object_type=ctx.get("object_type"),
                        object_id=ctx.get("object_id"),
                        relation=ctx.get("relation"),
                    )
                )
        else:
            result = self._find_policy_decision(policy_path, identity, ctx)
            if self.record_decisions:
                self.decisions.append(
                    Decision(
                        policy_path=policy_path,
                        decision_name=decision,
                        allowed=result,
                        identity_value=identity,
                        resource_context=ctx,
                        check_type="policy",
                    )
                )

        return result

    def find_decisions(self, **filters: Any) -> list[Decision]:
        """Find recorded decisions matching filters."""
        results = []
        for d in self.decisions:
            match = True
            for key, value in filters.items():
                if getattr(d, key, None) != value:
                    match = False
                    break
            if match:
                results.append(d)
        return results

    def clear_decisions(self) -> None:
        """Clear recorded decisions."""
        self.decisions.clear()


def install_mock(monkeypatch: Any, mock_config: MockTopazConfig, target: Any) -> None:
    """
    Patch a real TopazConfig to use mock behavior.

    Args:
        monkeypatch: pytest monkeypatch fixture
        mock_config: MockTopazConfig instance
        target: The real TopazConfig instance to patch
    """
    monkeypatch.setattr(target, "check_decision", mock_config.check_decision)


# Pytest fixtures (can be imported in conftest.py)
def pytest_configure(config: Any) -> None:
    """Register markers for pytest."""
    pass


# Pre-built fixtures for pytest_plugins usage
def mock_topaz_config_fixture():
    """Base MockTopazConfig fixture."""
    return MockTopazConfig(default_decision=True)


def allow_all_auth_fixture(monkeypatch: Any, mock_topaz_config: MockTopazConfig):
    """Allow all authorization checks."""
    mock_topaz_config.default_decision = True
    return mock_topaz_config


def deny_all_auth_fixture(monkeypatch: Any, mock_topaz_config: MockTopazConfig):
    """Deny all authorization checks."""
    mock_topaz_config.default_decision = False
    return mock_topaz_config
