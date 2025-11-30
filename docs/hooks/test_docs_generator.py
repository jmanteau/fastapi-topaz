"""
MkDocs hook to auto-generate e2e test documentation.

Parses test files and generates markdown tables with test descriptions.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path


def on_pre_build(config, **kwargs):
    """Generate test docs before MkDocs builds."""
    # Find the project root (where mkdocs.yml is)
    docs_dir = Path(config["docs_dir"])
    project_root = docs_dir.parent

    tests_dir = project_root / "integration-tests" / "e2e" / "tests"
    output_file = docs_dir / "reference" / "e2e-tests.md"

    if not tests_dir.exists():
        print(f"[test_docs_generator] Tests dir not found: {tests_dir}")
        return

    # Parse all test scenario files
    all_scenarios = {}
    for test_file in sorted(tests_dir.glob("test_scenario_*.py")):
        scenario_name, scenario_desc, tests = parse_test_file(test_file)
        if tests:
            all_scenarios[scenario_name] = {
                "description": scenario_desc,
                "tests": tests,
                "file": test_file.name,
            }

    # Generate markdown
    markdown = generate_markdown(all_scenarios)

    # Write output
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(markdown)
    print(f"[test_docs_generator] Generated {output_file} with {sum(len(s['tests']) for s in all_scenarios.values())} tests")


def parse_test_file(path: Path) -> tuple[str, str, list[dict]]:
    """
    Parse a test file and extract test information.

    Returns:
        (scenario_name, scenario_description, list of test dicts)
    """
    content = path.read_text()
    tree = ast.parse(content)

    # Extract module docstring for scenario description
    module_doc = ast.get_docstring(tree) or ""

    # Extract scenario name from filename
    # test_scenario_alice.py -> Alice's Workflow
    name_map = {
        "alice": "Alice's Workflow",
        "bob": "Bob's Workflow",
        "sharing": "Document Sharing",
        "authorization_failures": "Authorization Failures",
        "public_documents": "Public Documents",
    }
    file_stem = path.stem.replace("test_scenario_", "")
    scenario_name = name_map.get(file_stem, file_stem.replace("_", " ").title())

    # Extract test functions
    tests = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            docstring = ast.get_docstring(node) or ""
            parsed = parse_gherkin(docstring)
            tests.append({
                "name": node.name,
                "scenario": parsed.get("scenario", docstring.split("\n")[0] if docstring else ""),
                "given": parsed.get("given", ""),
                "when": parsed.get("when", ""),
                "then": parsed.get("then", ""),
            })

    return scenario_name, module_doc, tests


def parse_gherkin(docstring: str) -> dict:
    """
    Parse Gherkin-style docstring.

    Example:
        '''
        Scenario: Alice creates a folder
        Given: Alice is authenticated
        When: Alice creates a new folder
        Then: Folder is created successfully
        '''
    """
    result = {}

    patterns = {
        "scenario": r"Scenario:\s*(.+?)(?:\n|$)",
        "given": r"Given:\s*(.+?)(?:\n|$)",
        "when": r"When:\s*(.+?)(?:\n|$)",
        "then": r"Then:\s*(.+?)(?:\n|$)",
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, docstring, re.IGNORECASE)
        if match:
            result[key] = match.group(1).strip()

    return result


def generate_markdown(scenarios: dict) -> str:
    """Generate markdown documentation from parsed scenarios."""
    lines = [
        "# E2E Test Scenarios",
        "",
        "!!! info \"Auto-generated\"",
        "    This page is automatically generated from test docstrings.",
        "    Run `mkdocs serve` or `mkdocs build` to update.",
        "",
        f"**Total: {sum(len(s['tests']) for s in scenarios.values())} tests across {len(scenarios)} scenarios**",
        "",
    ]

    for scenario_name, data in scenarios.items():
        lines.append(f"## {scenario_name}")
        lines.append("")

        if data["description"]:
            # Extract first paragraph of module docstring
            desc_lines = data["description"].split("\n\n")[0].split("\n")
            for line in desc_lines:
                if line.strip() and not line.strip().startswith("Prerequisites"):
                    lines.append(f"> {line.strip()}")
            lines.append("")

        lines.append(f"*Source: `{data['file']}`*")
        lines.append("")

        # Generate table
        lines.append("| Test | Scenario | Given | When | Then |")
        lines.append("|------|----------|-------|------|------|")

        for test in data["tests"]:
            name = f"`{test['name']}`"
            scenario = test["scenario"] or "-"
            given = test["given"] or "-"
            when = test["when"] or "-"
            then = test["then"] or "-"
            lines.append(f"| {name} | {scenario} | {given} | {when} | {then} |")

        lines.append("")

    return "\n".join(lines)
