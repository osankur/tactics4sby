import sys
from typing import TextIO
import copy
import dataclasses
from dataclasses import dataclass
from collections import deque
from pathlib import Path

from logger import logger
import parser
import cell_graph
import configuration
from cell_graph import _strip_backslash


@dataclass
class SbyTask:
    name: str
    groups: list[str]


@dataclass
class SbyScript:
    strategy: parser.ProofStrategy
    cfg: configuration.Configuration
    verbose: bool = False
    verbose_yosys: bool = False

    DEFAULT_OPTION = "mode prove"
    DEFAULT_ENGINE = "smtbmc"

    tasks: list[SbyTask] = dataclasses.field(default_factory=list)
    options: dict[str, list[str]] = dataclasses.field(
        default_factory=lambda: {"": [SbyScript.DEFAULT_OPTION]}
    )
    engine: dict[str, list[str]] = dataclasses.field(
        default_factory=lambda: {"": [SbyScript.DEFAULT_ENGINE]}
    )
    script: list[tuple[str, list[str]]] = dataclasses.field(default_factory=list)

    # module contract proofs that have already been generated:
    _processed_modules: set[str] = dataclasses.field(default_factory=set)

    # task and group names used so far
    _task_and_group_names: set[str] = dataclasses.field(default_factory=set)

    # maps each task to its dependencies (typically its verification conditions)
    _task_dependencies: dict[str, list[str]] = dataclasses.field(default_factory=dict)

    def __post_init__(self):
        if self.strategy.multiclock:
            self.options[""] = ["multiclock on"]
        objective_queue = deque(self.strategy.objectives)
        while objective_queue:
            obj = objective_queue.popleft()
            objective_queue.extend(self.process_objective(obj))

    def _get_task_or_group_name(self, name: str) -> str:
        counter = 0
        while name in self._task_and_group_names:
            name = f"{name}_{counter}"
            counter += 1
        self._task_and_group_names.add(name)
        return name

    def add_task(self, task: str, groups: list[str], parent_tasks: list[str] = []):
        self.tasks.append(SbyTask(task, groups))
        for parent in parent_tasks:
            self._task_dependencies.setdefault(parent, []).append(task)

    def process_objective(self, objective: parser.Objective) -> list[parser.Objective]:
        """Generate tasks and subtasks for this objective, and return the list of objectives that appear in the subtree.

        Groups generated for the assume_guarantee tactic:
        - ``top``               : remove all submodule instances (except those inlined) by applying cutpoint on their outputs
        - _vc_``top``_top       : flatten, then remove submodule assumptions, and convert their assertions into assumptions
                                  then prove the top module's contract
        - _vc_``top``_``inst``  : focus on one instance; remove all other instances' assumptions, assume previous instances assertions,
                                  and remove next instances assertions; prove the current instance assumption

        Returns a list of further objectives to be processed.
        """
        logger.debug(f"Processing objective {objective.json_path:} {objective.top}")
        if objective.top in self._processed_modules:
            return []
        self._processed_modules.add(objective.top)

        new_objectives = []
        cg = cell_graph.get_cell_graphs(
            self.strategy.header, objective.top, self.strategy.multiclock, self.cfg
        )

        main_task = self._get_task_or_group_name(
            objective.top if objective.top else "objective"
        )
        objective_script = [line for line in self.strategy.header]
        objective_script.extend([f"hierarchy -top {objective.top}", "proc"])
        if objective.early_assert or objective.early_assume:
            objective_script.append(
                "chformal -early -assert "
                + ("-assume" if objective.early_assume else "")
            )
        self.script.append((main_task, objective_script))

        if objective.tactic is None:
            self.add_task(main_task, [])
        elif isinstance(objective.tactic, parser.AssumeGuaranteeTactic):
            all_module_names = set(
                str(_strip_backslash(str(k))) for k in cg[objective.top].design.modules_
            )
            user_defined_cells = list(
                filter(
                    lambda cell: cell.name[0] == "\\",
                    cg[objective.top].top_module.cells_.values(),
                )
            )
            all_submodule_names = all_module_names & set(
                _strip_backslash(str(cell.type))
                for cell in user_defined_cells
                if cell.type[0] == "\\"
            )
            if objective.tactic.submodules is not None:
                assert set(objective.tactic.submodules.keys()).issubset(
                    all_submodule_names
                ), (
                    f"Following modules do not appear inside module {objective.top}: {set(objective.tactic.submodules.keys()).difference(all_submodule_names)}"
                )
            participating_submodule_names = (
                all_submodule_names
                if objective.tactic.submodules is None
                else set(objective.tactic.submodules.keys())
            )

            if objective.tactic.instances:
                user_defined_cell_names = set(
                    str(cell.name) for cell in user_defined_cells
                )
                for inst in objective.tactic.instances:
                    if f"\\{inst}" not in user_defined_cell_names:
                        raise Exception(
                            f"{objective.tactic.json_path}: no instance {inst} found in module {objective.top})"
                        )
                    inst_cell = cg[objective.top].top_module.cell(f"\\{inst}")
                    if (
                        inst_cell.type != "$assert$"
                        and _strip_backslash(inst_cell.module.name)
                        not in all_module_names
                    ):
                        raise Exception(
                            f"{objective.tactic.json_path}: {inst} is neither a module instance or an assert"
                        )

            # instances whose modules appear in participating_submodules
            participating_submodules_instances: set[str] = set()
            for cell in user_defined_cells:
                if cell.type[0] == "\\":
                    cell_type = _strip_backslash(cell.type)
                    if cell_type in participating_submodule_names:
                        participating_submodules_instances.add(
                            _strip_backslash(cell.name)
                        )

            if objective.tactic.instances:
                participating_instance_names = tuple(objective.tactic.instances)
                inlined_instance_names = tuple(
                    participating_submodules_instances
                    - set(participating_instance_names)
                )
            elif objective.tactic.inline:
                assert objective.tactic.auto
                inlined_instance_names = tuple(objective.tactic.inline)
                participating_instance_names = tuple(
                    participating_submodules_instances - set(inlined_instance_names)
                )
            else:
                inlined_instance_names = []
                participating_instance_names = participating_submodules_instances

            logger.debug(
                f"{objective.top}: Generating assume-guarantee verification conditions"
            )
            logger.debug(
                f"\tFollowing submodules participate in assume-guarantee decomposition: {participating_submodule_names}"
            )
            logger.debug(
                f"\tAll instances of the participating submodules: {participating_submodules_instances}"
            )
            logger.debug(f"\tInlined: {inlined_instance_names}")
            logger.debug(f"\tDecomposed: {participating_instance_names}")

            if objective.tactic.auto:
                depgraph = cg[objective.top].get_module_dependency_graph(
                    set(participating_instance_names)
                )
                logger.debug(f"\tInstance dependency relation:\n{depgraph}")
                if self.cfg.verbosity >= 2:
                    depgraph.write_module_dependencies_to_dot(
                        Path((self.cfg.tmpdir / (f"instance_deps_{objective.top}.dot")))
                    )
                ordered_instances = depgraph.get_topological_ordering()
            else:
                ordered_instances = list(
                    cg[objective.top].top_module.cell(f"\\{name}")
                    for name in participating_instance_names
                )
            logger.debug(
                f"\tAssume-guarantee order (auto: {objective.tactic.auto}): {[inst.name for inst in ordered_instances]}"
            )

            def _mark_level1_child_check_cells(cells, attribute: str) -> list[str]:
                script = []
                for cell in cells:
                    exclude_list = []
                    if cell.type == "$assert":
                        continue
                    submodule_name = _strip_backslash(cell.type)
                    cell_name = _strip_backslash(cell.name)
                    for inst_cell in cg[submodule_name].submodule_instance_cells:
                        inst_cell_name = _strip_backslash(inst_cell.name)
                        exclude_list.append(
                            f"{objective.top}/{cell_name}.{inst_cell_name}.*"
                        )
                        exclude_list.extend(
                            [
                                f"{objective.top}/$flatten\\{cell_name}.{inst_cell_name}.*",
                                f"{objective.top}/$flatten\\{cell_name}.\\{inst_cell_name}.*",
                            ]
                        )
                    script.append(
                        f"setattr -set _ag_vc_flattened 1 {objective.top}/{cell_name}.* {objective.top}/$flatten\\{cell_name}.* %u {' %d '.join(exclude_list)} {'%d' if exclude_list else ''}"
                    )
                return script

            top_ag_task = self._get_task_or_group_name(f"_vc_{main_task}_top")
            top_ag_script = [
                "chformal -remove -cover -live",
                "# Mark check cells at the top level:",
                f"setattr -set _ag_vc_top 1 {objective.top}/* t:$check %i",
                "# Flatten cells participating to assume-guarantee:",
                "flatten "
                + " ".join(
                    [f"{objective.top}/{s}" for s in participating_instance_names]
                ),
                "# Mark all check cells of flattened submodules at level 1 but not below:",
            ]
            top_ag_script.extend(
                _mark_level1_child_check_cells(ordered_instances, "_ag_vc_flattened")
            )
            top_ag_script.extend(
                [
                    "flatten",
                    "# Remove all unmarked check cells:",
                    "chformal -remove -assume -assert a:_ag_vc_flattened=1 a:_ag_vc_top=1 %u %n",
                    "# Remove all assumptions of submodules and convert asserts into assumes",
                    "chformal -remove -assume a:_ag_vc_flattened=1",
                    "chformal -assert -assert2assume a:_ag_vc_flattened=1",
                    "log Remaining assumes for this VC:",
                    "select r:FLAVOR=assume -list",
                    "log Remaining asserts for this VC:",
                    "select r:FLAVOR=assert -list",
                ]
            )
            top_ag_script.append("opt_clean -purge")

            def _subcell_names_of_cell(cell) -> str:
                if cell.type == "$assert":
                    return f"{objective.top}/{_strip_backslash(cell.name)}"
                else:
                    return f"{objective.top}/{_strip_backslash(cell.name)}.* {objective.top}/$flatten\\{_strip_backslash(cell.name)}.* %u"

            top_ag_script.extend(
                [
                    f"select -module {objective.top}",
                    f"show -stretch -prefix {objective.top} -format svg",
                ]
            )
            self.script.append((top_ag_task, top_ag_script))
            # Task: disconnect submodules first (main_task), then prove the top contract
            self.add_task(main_task, [top_ag_task], [])

            previous_cells = []
            next_cells = copy.copy(ordered_instances)
            while next_cells:
                cell = next_cells.pop(0)
                cell_name = _strip_backslash(cell.name)
                inst_ag_task = self._get_task_or_group_name(
                    f"_vc_{main_task}_{cell_name}_"
                )
                inst_ag_script = [
                    "chformal -remove -cover -live",
                    "# Remove all top-level asserts and flatten:",
                    f"chformal -assert -remove {objective.top}/*",
                    "# Mark assume cells at the top level:",
                    f"setattr -set _ag_vc_top 1 {objective.top}/* t:$check %i",
                    "flatten",
                ]

                inst_ag_script.extend(
                    _mark_level1_child_check_cells(
                        ordered_instances, "_vc_ag_flattened"
                    )
                )
                inst_ag_script.extend(
                    [
                        "# Remove all unmarked check cells:",
                        "chformal -remove -assume -assert a:_ag_vc_flattened=1 a:_ag_vc_top=1 %u %n",
                    ]
                )
                # remove previous instances' assumptions, and assume their assertions
                for prev_cell in previous_cells:
                    inst_ag_script.extend(
                        [
                            f"chformal -assume -remove {_subcell_names_of_cell(prev_cell)}",
                            f"chformal -assert -assert2assume {_subcell_names_of_cell(prev_cell)}",
                        ]
                    )
                # prove current cell's assumptions
                inst_ag_script.extend(
                    [
                        "# Remove current goal's assert, and prove its assume",
                        f"chformal -remove -assert {_subcell_names_of_cell(cell)}",
                        f"chformal -assume -assume2assert {_subcell_names_of_cell(cell)} # vc goal",
                    ]
                )
                # remove next cells' assumptions and assertions
                for next_cell in next_cells:
                    inst_ag_script.append(
                        f"chformal -assert -assume -remove {_subcell_names_of_cell(next_cell)}"
                    )
                inst_ag_script.extend(
                    [
                        "log Remaining assumes for this VC:",
                        "select r:FLAVOR=assume -list",
                        "log Remaining asserts for this VC:",
                        "select r:FLAVOR=assert -list",
                        f"select -module {objective.top}",
                        f"show -stretch -prefix {inst_ag_task} -format svg",
                    ]
                )

                self.script.append((inst_ag_task, inst_ag_script))
                self.add_task(inst_ag_task, [main_task], [main_task])
                previous_cells.append(cell)
            if objective.tactic.submodules:
                for subm in objective.tactic.submodules.values():
                    new_objectives.append(subm)
        else:
            raise Exception(
                f"{objective.tactic.json_path}: only assume-guarantee tactic is currently supported"
            )
        return new_objectives

    def dump(self, f: TextIO | None = None):
        """Write the .sby file to an already open file object ``f`` (e.g. an
        open file or ``sys.stdout``)."""
        if f is None:
            f = sys.stdout

        def _dump_dict(content: dict[str, list[str]], f):
            if "" in content:
                print("\n".join(content[""]), file=f)
            for group, opt in content.items():
                if group:
                    print(f"{group}:", file=f)
                    print("\n".join(opt), file=f)
                    print("--", file=f)
            print("", file=f)

        print("[tasks]", file=f)
        for task in self.tasks:
            print(f"{task.name} {' '.join(task.groups)}", file=f)
        print("", file=f)
        print("[options]", file=f)
        _dump_dict(self.options, f)
        print("[engines]", file=f)
        _dump_dict(self.engine, f)
        print("[script]", file=f)
        for group, content in self.script:
            print(f"{group}:", file=f)
            print("\n".join(content), file=f)
            print("--", file=f)
        print("[files]", file=f)
        print("\n".join(self.strategy.files), file=f)
