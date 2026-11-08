"""Structural tests over the playbooks and roles.

These do not need a cluster: they parse the same YAML Ansible will, and they
catch the three failure classes that have actually bitten this framework:

* a role or include that names a file which does not exist;
* a playbook that names a role which does not exist;
* a ``dgx_*`` variable that is referenced but never defined (the undefined-
  variable class, which only shows up at runtime on the target).
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLES = ROOT / "roles"
PLAYBOOKS = ROOT / "playbooks"
GROUP_VARS = ROOT / "inventory" / "group_vars" / "all.yml"

DGX_VAR = re.compile(r"\bdgx_[a-z0-9_]+\b")
URL = re.compile(r"https?://\S+")

# Names that look like variables but are not: they appear inside repository
# URLs and image paths, which the URL strip below does not always reach, and
# role names appear in a playbook's ``roles:`` list.
NOT_VARIABLES = {
    "dgx_spark_kubeadm_deployment",
    *(role.name for role in ROLES.iterdir() if role.is_dir()),
}


def load(path: Path):
    with path.open() as handle:
        return yaml.safe_load(handle)


def yaml_files(base: Path):
    return sorted(p for p in base.rglob("*.yml") if p.is_file())


def walk_tasks(node):
    """Yield every mapping in a task tree."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk_tasks(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk_tasks(item)


def task_files(role: Path):
    tasks_dir = role / "tasks"
    if not tasks_dir.is_dir():
        return []
    return sorted(tasks_dir.rglob("*.yml"))


def defined_variables() -> set[str]:
    names: set[str] = set()

    def keys_of(path: Path) -> None:
        if not path.is_file():
            return
        data = load(path)
        if isinstance(data, dict):
            names.update(data)

    keys_of(GROUP_VARS)
    scanned = list(yaml_files(PLAYBOOKS))
    for role in sorted(ROLES.iterdir()):
        if not role.is_dir():
            continue
        keys_of(role / "defaults" / "main.yml")
        keys_of(role / "vars" / "main.yml")
        scanned += task_files(role)
    for path in scanned:
        for node in walk_tasks(load(path) or []):
            for key, value in node.items():
                # Match set_fact whether or not it is fully qualified.
                if key == "set_fact" or key.endswith(".set_fact"):
                    if isinstance(value, dict):
                        names.update(value)
                # Task- and play-level vars are definitions too.
                if key == "vars" and isinstance(value, dict):
                    names.update(value)
            if isinstance(node.get("register"), str):
                names.add(node["register"])
            loop_control = node.get("loop_control")
            if isinstance(loop_control, dict) and "loop_var" in loop_control:
                names.add(loop_control["loop_var"])
    return names


def referenced_variables() -> dict[str, set[str]]:
    """Return {variable: {files that mention it}}."""
    found: dict[str, set[str]] = {}
    paths = list(yaml_files(PLAYBOOKS)) + list(yaml_files(ROLES))
    paths += sorted(ROLES.rglob("*.j2"))
    for path in paths:
        text = path.read_text()
        text = URL.sub("", text)
        # Templates mention things like ``DGX10-OK``; only names with the
        # dgx_ prefix are candidates, and the regex above is case-sensitive.
        for name in DGX_VAR.findall(text):
            if name not in NOT_VARIABLES:
                found.setdefault(name, set()).add(str(path.relative_to(ROOT)))
    return found


class RoleTests(unittest.TestCase):
    def test_every_role_has_parsable_tasks(self) -> None:
        for role in sorted(ROLES.iterdir()):
            if not role.is_dir():
                continue
            main = role / "tasks" / "main.yml"
            self.assertTrue(main.is_file(), f"{role.name} has no tasks/main.yml")
            data = load(main)
            self.assertIsInstance(data, list, f"{role.name}/tasks/main.yml is not a list")

    def test_every_template_and_copy_source_exists(self) -> None:
        for role in sorted(ROLES.iterdir()):
            if not role.is_dir():
                continue
            for path in task_files(role):
                for node in walk_tasks(load(path) or []):
                    for key in ("template", "copy"):
                        spec = node.get(key)
                        if not isinstance(spec, dict):
                            continue
                        src = spec.get("src")
                        if not isinstance(src, str) or src.startswith("{{"):
                            continue
                        candidates = [
                            role / "templates" / src,
                            role / "files" / src,
                        ]
                        self.assertTrue(
                            any(c.is_file() for c in candidates),
                            f"{path.relative_to(ROOT)}: {key} src {src!r} not found in {role.name}",
                        )

    def test_every_include_target_exists(self) -> None:
        for role in sorted(ROLES.iterdir()):
            if not role.is_dir():
                continue
            for path in task_files(role):
                for node in walk_tasks(load(path) or []):
                    for key in ("include_tasks", "import_tasks"):
                        target = node.get(key)
                        if not isinstance(target, str) or target.startswith("{{"):
                            continue
                        candidate = (path.parent / target).resolve()
                        self.assertTrue(
                            candidate.is_file(),
                            f"{path.relative_to(ROOT)}: {key} target {target!r} not found",
                        )


class PlaybookTests(unittest.TestCase):
    def test_every_playbook_parses_and_names_real_roles(self) -> None:
        for path in yaml_files(PLAYBOOKS):
            data = load(path)
            self.assertIsInstance(data, list, f"{path.name} is not a list of plays")
            for play in data:
                if not isinstance(play, dict):
                    continue
                for entry in play.get("roles") or []:
                    name = entry if isinstance(entry, str) else entry.get("role")
                    if not isinstance(name, str) or name.startswith("{{"):
                        continue
                    self.assertTrue(
                        (ROLES / name).is_dir(),
                        f"{path.name}: role {name!r} does not exist",
                    )

    def test_every_imported_playbook_exists(self) -> None:
        for path in yaml_files(PLAYBOOKS):
            for play in load(path) or []:
                if not isinstance(play, dict):
                    continue
                for key in ("import_playbook", "include"):
                    target = play.get(key)
                    if not isinstance(target, str) or target.startswith("{{"):
                        continue
                    candidate = (path.parent / target).resolve()
                    self.assertTrue(
                        candidate.is_file(),
                        f"{path.name}: {key} target {target!r} not found",
                    )


class VariableTests(unittest.TestCase):
    def test_group_vars_parse_as_a_mapping(self) -> None:
        data = load(GROUP_VARS)
        self.assertIsInstance(data, dict)
        self.assertIn("dgx_repo_ref", data)

    def test_every_referenced_dgx_variable_is_defined(self) -> None:
        defined = defined_variables()
        referenced = referenced_variables()
        undefined = {
            name: sorted(files)
            for name, files in referenced.items()
            if name not in defined
        }
        message = "\n".join(
            f"  {name}: {', '.join(files[:3])}" for name, files in sorted(undefined.items())
        )
        self.assertFalse(
            undefined,
            "dgx_* variables are referenced but never defined:\n" + message,
        )


if __name__ == "__main__":
    unittest.main()
