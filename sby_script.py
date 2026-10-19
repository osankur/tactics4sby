import sys
from typing import TextIO
import json
import copy
import os
from dataclasses import dataclass, field
import subprocess
from pathlib import Path
import configuration


STATUS_BITS: dict[str, int] = {
    "PASS": 1,
    "FAIL": 2,
    "UNKNOWN": 4,
    "TIMEOUT": 8,
    "ERROR": 16,
    "CANCELLED": 32,
}


def status_to_code(status: str):
    if status == "PASS":
        return 1
    if status == "FAIL":
        return 2
    if status == "UNKNOWN":
        return 4
    if status == "TIMEOUT":
        return 8
    if status == "ERROR":
        return 16
    if status == "CANCELLED":
        return 32

    raise Exception(f"Unknown sby status: {status}")


STATUS_ICONS: dict[str, str] = {
    "PASS": "\u2705",  # ✅ green check mark
    "FAIL": "\u274c",  # ❌ red cross
    "UNKNOWN": "\u2754",  # ❔ question mark ornament (bluish/grey)
    "TIMEOUT": "\u231b",  # ⌛ hourglass
    "ERROR": "\U0001f4a5",  # 💥 collision
    "CANCELLED": "\U0001f6ab",  # 🚫 prohibited
}


def status_to_icone(status: str | None):
    """Return a short status icon for ``status``.

    Falls back to a middle dot for unknown or unset (``None``) statuses, e.g.
    for a verification condition whose results have not been annotated yet.
    """
    return STATUS_ICONS.get(status, "\u00b7")  # ·


def code_to_statuses(code: int) -> list[str]:
    return [status for status, bit in STATUS_BITS.items() if code & bit]


@dataclass
class SbyResult:
    taskstatus: dict[str, str] = field(default_factory=lambda: dict())
    vc_results: list[dict[str, str]] = field(default_factory=lambda: [])


@dataclass
class VerificationCondition:
    VC_PREFIX = "_vc_"
    name: str
    tactic: str
    children: list["VerificationCondition"] = field(default_factory=lambda: [])
    options: list[str] = field(default_factory=lambda: [])
    engines: list[str] = field(default_factory=lambda: [])
    script: list[str] = field(default_factory=lambda: [])

    status: str | None = None
    vc_results: list[dict[str, str]] = field(default_factory=lambda: [])

    def __post_init__(self):
        self.name = f"{self.VC_PREFIX}{self.name}"
        for vc in self.children:
            assert vc

    def annotate(self, sby_result: SbyResult):
        for vc in self.children:
            vc.annotate(sby_result)
        children_status = [vc.status for vc in self.children]
        if self.children == []:
            self.status = sby_result.taskstatus.get(self.name, "UNKNOWN")
            self.vc_results = [
                r for r in sby_result.vc_results if r["task_name"] == self.name
            ]
        else:
            if "FAIL" in children_status:
                self.status = "FAIL"
            elif all(map(lambda x: x == "PASS", children_status)):
                self.status = "PASS"
            else:
                self.status = "UNKNOWN"


@dataclass
class SbyScript:
    options: list[str]
    engines: list[str]
    script: list[str]
    files: list[str]
    vcs: list[VerificationCondition]
    sby_file: Path
    cfg: configuration.Configuration
    result: SbyResult | None = None
    DEFAULT_OPTIONS: tuple[str, ...] = ("mode prove",)
    DEFAULT_ENGINES: tuple[str, ...] = ("smtbmc",)

    def dump(self, f: TextIO | None = None):
        """Write the .sby file to an already open file object ``f`` (e.g. an
        open file or ``sys.stdout``)."""
        if f is None:
            f = sys.stdout

        section_options = copy.copy(self.options)
        section_script = []
        section_engines = copy.copy(self.engines)
        section_tasks = []

        def add_group(group_name: str, group_content: list[str], section: list[str]):
            if group_content:
                if len(group_content) == 1:
                    section.append(f"{group_name}: {group_content[0]}")
                else:
                    section.append(f"{group_name}:")
                    section.extend(group_content)
                    section.append("--")

        def traverse(
            vc: VerificationCondition,
            parent_groups: list[str],
            inherited_options: list[str],
            inherited_engines: list[str],
        ):
            """
            either there is a global options & engines, or each task must specify these
            """
            options = vc.options if vc.options else inherited_options
            engines = vc.engines if vc.engines else inherited_engines
            add_group(vc.name, vc.script, section_script)
            if vc.children == []:
                add_group(
                    vc.name,
                    options if options else list(self.DEFAULT_OPTIONS),
                    section_options,
                )
                add_group(
                    vc.name,
                    engines if engines else list(self.DEFAULT_ENGINES),
                    section_engines,
                )
                section_tasks.append(f"{vc.name} {' '.join(parent_groups)}")
            else:
                next_parent_groups = (
                    [vc.name] + parent_groups
                    if vc.options or vc.script or vc.engines
                    else parent_groups
                )
                for subvc in vc.children:
                    traverse(subvc, next_parent_groups, options, engines)

        for vc in self.vcs:
            traverse(vc, [], [], [])

        def print_section(name: str, content: list[str]):
            print(f"[{name}]", file=f)
            for line in content:
                print(line, file=f)
            print("", file=f)

        print_section("tasks", section_tasks)
        print_section("options", section_options)
        print_section("engines", section_engines)
        print_section("script", section_script)
        print_section("files", self.files)

    def to_string(self, show_details: bool = True):
        lines = []

        def add_section(title: str, values: list[str]) -> None:
            if values:
                lines.append(f"  {title}:")
                lines.extend(f"    {value}" for value in values)

        add_section("Options", self.options)
        add_section("Engines", self.engines)
        add_section("Script", self.script)

        def vc_label(vc: VerificationCondition) -> str:
            tactic_string = "" if vc.tactic == "" else f"(by {vc.tactic})"
            return f"[{status_to_icone(vc.status)}] {vc.name} {tactic_string}"

        def vc_details(vc: VerificationCondition) -> list[str]:
            details = []
            if vc.options:
                details.append(f"options: {vc.options}")
            if vc.engines:
                details.append(f"engines: {vc.engines}")
            return details

        def render_vc(
            vc: VerificationCondition, prefix: str, connector: str
        ) -> list[str]:
            """Render ``vc`` and its descendants as pstree-like lines.

            ``prefix`` is the indentation before the node's connector, and
            ``connector`` is ``""`` for a root node, ``"├─"`` for a non-last
            child, or ``"└─"`` for a last child. The node's junction column is
            ``len(prefix) + len(connector)``; both its detail lines and its
            children's connectors are aligned to that column.
            """
            label = vc_label(vc)
            children = vc.children
            n = len(children)

            is_toplevel = prefix == "" and connector in ("┌", "├", "└")

            if is_toplevel:
                if n > 0:
                    prelabel = "┬"
                else:
                    prelabel = "" if connector == "└" else "─"
            else:
                prelabel = "┬" if n > 0 else " "

            result: list[str] = [f"{prefix}{connector}{prelabel}{label}"]

            # Every child is printed on its own line, even when there is only
            # one. Non-last children start with "├", the last one with "└".
            # Children's connectors line up with this node's junction column;
            # the vertical bar is carried down for non-last children so
            # subtrees stay connected. Root children have no bar above them, so
            # they are indented with spaces only.
            if connector == "":
                child_prefix = ""
            elif connector.startswith("└"):
                child_prefix = prefix + " " * len(connector)
            else:
                child_prefix = prefix + "│" + " " * (len(connector) - 1)

            # Options/engines/script are shown on their own lines, aligned with
            # the node's junction column. A vertical bar is drawn when the node
            # has children so the subtree stays connected.
            detail_prefix = "│ " if n > 0 else "  "
            if show_details:
                for detail in vc_details(vc):
                    result.append(child_prefix + detail_prefix + "  " + detail)
            vc_dir = self.sby_file.parent / f"{self.sby_file.stem}_{vc.name}"
            vc_dir = Path(os.path.relpath(vc_dir, self.cfg.invocation_dir))
            result.append(child_prefix + detail_prefix + f"  sby logs: {vc_dir}")
            for r in vc.vc_results:
                if r["status"] == "FAIL":
                    result.append(
                        child_prefix
                        + detail_prefix
                        + f"failing {r['kind']}: {r['name']} at {r['location']}"
                    )
                    result.append(child_prefix + detail_prefix + f"trace: {r['trace']}")
            if vc.status == "ERROR":
                result.append(
                    child_prefix
                    + detail_prefix
                    + f"error: see {vc_dir / 'logfile.txt'}"
                )
            for i, child in enumerate(children):
                child_connector = "└─" if i == n - 1 else "├─"
                result.extend(render_vc(child, child_prefix, child_connector))

            return result

        if self.vcs:
            for i, vc in enumerate(self.vcs):
                if i == 0:
                    connector = "┌"
                elif i == len(self.vcs) - 1:
                    connector = "└"
                else:
                    connector = "├"
                lines.extend(render_vc(vc, "", connector))

        return "\n".join(lines)

    def annotate_with_results(self, sby_result: SbyResult):
        """Annotate VC tree with sby results by propagating status bottom up"""
        for vc in self.vcs:
            vc.annotate(sby_result)

    def __str__(self):
        return self.to_string()

    def run(self, task_to_run: str | None = None) -> int:
        """Run sby on ``sby_file`` and store the parsed status records."""
        if not self.sby_file.exists():
            raise Exception(
                f"Attempting to run sby on file {self.sby_file} that has not been written"
            )
        sby_exec = subprocess.run(
            ["sby", "-f", str(self.sby_file)]
            + ([] if task_to_run is None else [task_to_run]),
            stdout=None if self.cfg.verbose_sby else subprocess.DEVNULL,
            stderr=None if self.cfg.verbose_sby else subprocess.DEVNULL,
            check=False,
        )
        sby_taskstatus_result = subprocess.run(
            ["sby", "-f", "--taskstatus", str(self.sby_file)],
            stdout=subprocess.PIPE,
            stderr=None if self.cfg.verbose_sby else subprocess.DEVNULL,
            check=False,
            text=True,
        )
        status = dict()
        for line in sby_taskstatus_result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            fields = line.split(" ")
            assert len(fields) == 2, f"Unexpected output by --taskstatus: {fields}"
            if fields[1] == "UNKNOWN":
                # In the cases below, the taskstatus appears as unknown
                task_dir = self.sby_file.parent / f"{self.sby_file.stem}_{fields[0]}"
                if (task_dir / "ERROR").exists():
                    fields[1] = "ERROR"
                elif (task_dir / "CANCELLED").exists():
                    fields[1] = "CANCELLED"
                elif (task_dir / "TIMEOUT").exists():
                    fields[1] = "TIMEOUT"
            status[fields[0]] = fields[1]
        sby_statusfmt_result = subprocess.run(
            ["sby", "-f", "--statusfmt", "jsonl", str(self.sby_file)],
            stdout=subprocess.PIPE,
            stderr=None if self.cfg.verbose_sby else subprocess.DEVNULL,
            check=True,
            text=True,
        )
        records: list[dict] = []
        for line in sby_statusfmt_result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
        self.result = SbyResult(status, records)
        self.annotate_with_results(self.result)
        return sby_exec.returncode
