"""
Command-line interface for fastapi-topaz.

Provides commands for policy generation, validation, and documentation.
"""
from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path


def import_app(app_path: str):
    """Import FastAPI app from module:attribute format."""
    try:
        module_path, attr_name = app_path.rsplit(":", 1)
    except ValueError:
        print(f"Error: Invalid app path '{app_path}'. Use format 'module.path:app'")
        sys.exit(1)

    try:
        module = importlib.import_module(module_path)
        return getattr(module, attr_name)
    except (ImportError, AttributeError) as e:
        print(f"Error importing app: {e}")
        sys.exit(1)


def import_config(config_path: str):
    """Import TopazConfig from module:attribute format."""
    try:
        module_path, attr_name = config_path.rsplit(":", 1)
        module = importlib.import_module(module_path)
        return getattr(module, attr_name)
    except Exception as e:
        print(f"Error importing config: {e}")
        sys.exit(1)


def cmd_generate_policies(args: argparse.Namespace) -> int:
    """Generate policy skeletons from FastAPI routes."""
    from .codegen import PolicyTemplate, generate_policies

    app = import_app(args.app)

    # Create minimal config if not provided
    if args.config:
        config = import_config(args.config)
    else:
        from aserto.client import AuthorizerOptions, Identity, IdentityType

        from .dependencies import TopazConfig

        config = TopazConfig(
            authorizer_options=AuthorizerOptions(url="localhost:8282"),
            policy_path_root=args.root or "app",
            identity_provider=lambda r: Identity(
                type=IdentityType.IDENTITY_TYPE_NONE, value=""
            ),
            policy_instance_name="generated",
        )

    template = PolicyTemplate(
        default_decision=False,
        include_comments=True,
        include_route_info=True,
    )

    if args.dry_run:
        policies = generate_policies(app, config, template=template)
        print(f"Would generate {len(policies)} policies:")
        for path in sorted(policies.keys()):
            print(f"  {path}")
        return 0

    output = Path(args.output) if args.output else Path("policies")
    policies = generate_policies(app, config, output_dir=output, template=template)

    print(f"Generated {len(policies)} policies in {output}/")
    for path in sorted(policies.keys()):
        print(f"  ✓ {path}")

    return 0


def cmd_policy_diff(args: argparse.Namespace) -> int:
    """Compare routes against existing policies."""
    from .codegen import policy_diff

    app = import_app(args.app)

    if args.config:
        config = import_config(args.config)
    else:
        from aserto.client import AuthorizerOptions, Identity, IdentityType

        from .dependencies import TopazConfig

        config = TopazConfig(
            authorizer_options=AuthorizerOptions(url="localhost:8282"),
            policy_path_root=args.root or "app",
            identity_provider=lambda r: Identity(
                type=IdentityType.IDENTITY_TYPE_NONE, value=""
            ),
            policy_instance_name="generated",
        )

    policies_dir = Path(args.policies) if args.policies else Path("policies")
    diff = policy_diff(app, config, policies_dir)

    if diff.missing:
        print(f"\n❌ Missing policies ({len(diff.missing)}):")
        for m in diff.missing:
            print(f"   - {m.policy_path}")
            print(f"     Route: {m.method} {m.path}")

    if diff.orphaned:
        print(f"\n⚠️  Orphaned policies ({len(diff.orphaned)}):")
        for o in diff.orphaned:
            print(f"   - {o}")

    if diff.valid:
        print(f"\n✓ Valid policies: {len(diff.valid)}")

    if diff.has_issues:
        print(f"\nSummary: {len(diff.missing)} missing, {len(diff.orphaned)} orphaned")
        return 1 if args.strict or diff.missing else 0

    print("\n✓ All policies are in sync!")
    return 0


def cmd_policy_map(args: argparse.Namespace) -> int:
    """Generate route-to-policy mapping documentation."""
    from .codegen import scan_routes

    app = import_app(args.app)
    root = args.root or "app"
    routes = scan_routes(app, root)

    if args.format == "markdown":
        print("| Route | Method | Policy Path | Auth Type |")
        print("|-------|--------|-------------|-----------|")
        for r in sorted(routes, key=lambda x: (x["path"], x["method"])):
            print(f"| {r['path']} | {r['method']} | {r['policy_path']} | {r['auth_type']} |")
    else:
        for r in sorted(routes, key=lambda x: (x["path"], x["method"])):
            print(f"{r['method']:8} {r['path']:40} -> {r['policy_path']}")

    return 0


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="fastapi-topaz",
        description="FastAPI Topaz authorization utilities",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # generate-policies
    gen = subparsers.add_parser(
        "generate-policies", help="Generate Rego policy skeletons from routes"
    )
    gen.add_argument("--app", required=True, help="FastAPI app (module:attribute)")
    gen.add_argument("--output", "-o", help="Output directory (default: policies/)")
    gen.add_argument("--config", help="TopazConfig (module:attribute)")
    gen.add_argument("--root", help="Policy path root (default: app)")
    gen.add_argument("--dry-run", action="store_true", help="Preview without writing")
    gen.set_defaults(func=cmd_generate_policies)

    # policy-diff
    diff = subparsers.add_parser(
        "policy-diff", help="Compare routes against existing policies"
    )
    diff.add_argument("--app", required=True, help="FastAPI app (module:attribute)")
    diff.add_argument("--policies", "-p", help="Policies directory (default: policies/)")
    diff.add_argument("--config", help="TopazConfig (module:attribute)")
    diff.add_argument("--root", help="Policy path root (default: app)")
    diff.add_argument("--strict", action="store_true", help="Fail on orphaned policies too")
    diff.set_defaults(func=cmd_policy_diff)

    # policy-map
    pmap = subparsers.add_parser(
        "policy-map", help="Generate route-to-policy mapping"
    )
    pmap.add_argument("--app", required=True, help="FastAPI app (module:attribute)")
    pmap.add_argument("--root", help="Policy path root (default: app)")
    pmap.add_argument("--format", choices=["text", "markdown"], default="text")
    pmap.set_defaults(func=cmd_policy_map)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
