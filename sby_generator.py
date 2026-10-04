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
from cell_graph import _strip_backslash, CellGraph


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
        proven_tops = {o.top for o in self.strategy.objectives}
        for objective in self.strategy.objectives:
            self.process_objective(objective, proven_tops)

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

    def process_tactic(
        self,
        tactic: parser.Tactic,
        parent_task: str,
        task_script: list[str],
        task_groups: list[str],
        cg: dict[str, CellGraph],
        parent_objective: parser.Objective,
        proven_tops: set[str],
    ):
        """
        Explore the tactic tree recursively, and produce tasks at each leaf
        """
        if isinstance(tactic, parser.AssumeGuaranteeTactic):
            all_module_names = set(
                str(_strip_backslash(str(k)))
                for k in cg[parent_objective.top].design.modules_
            )
            user_defined_cells = list(
                filter(
                    lambda cell: cell.name[0] == "\\"
                    and (cell.type[0] == "\\" or cell.type[0] == "$assert"),
                    cg[parent_objective.top].top_module.cells_.values(),
                )
            )
            user_defined_module_instance_cells = list(
                filter(lambda cell: cell.type[0] == "\\", user_defined_cells)
            )
            user_defined_cell_names = set(
                _strip_backslash(cell.name) for cell in user_defined_cells
            )
            all_submodule_names = all_module_names & set(
                _strip_backslash(str(cell.type))
                for cell in user_defined_cells
                if cell.type[0] == "\\"
            )

            instances = (
                tactic.instances
                if tactic.instances
                else tuple(
                    parser.Instance(name=name, tactic=tactic.tactic)
                    for name in all_submodule_names
                )
            )

            inline_names = set()
            if tactic.inline:
                assert tactic.auto
                inline_names = set(tactic.inline)
            participating_names = []
            participating_assert_names = []
            participating_submodule_instance_names = []
            for inst in instances:
                if inst.name in user_defined_cell_names:
                    # the cell name appears in inline
                    if inst.name in inline_names:
                        continue
                    inst_cell = cg[parent_objective.top].top_module.cell(
                        f"\\{inst.name}"
                    )
                    if inst_cell.type == "$assert":
                        participating_assert_names.append(inst.name)
                        participating_names.append(inst.name)
                    elif (
                        inst_cell.type[0] == "\\"
                        and _strip_backslash(inst_cell.type) in all_submodule_names
                    ):
                        participating_submodule_instance_names.append(inst.name)
                        participating_names.append(inst.name)
                        if _strip_backslash(inst_cell.type) not in proven_tops:
                            raise Exception(
                                f"{tactic.json_path}: {inst.name} is an instance of module {_strip_backslash(inst_cell.type)} but there is no objective for this module."
                            )
                    else:
                        raise Exception(
                            f"{tactic.json_path}: {inst.name} (of type {inst_cell.type}) is neither a module instance or an assert"
                        )
                elif inst.name in all_submodule_names:
                    # the module name appears in inline
                    if inst.name in inline_names:
                        continue
                    if inst.name not in proven_tops:
                        raise Exception(
                            f"{tactic.json_path}: Instances of module {inst.name} appear here but there is no objective for this module."
                        )
                    for cell in user_defined_module_instance_cells:
                        if _strip_backslash(cell.type) == inst.name:
                            cell_name = _strip_backslash(cell.name)
                            # the cell name appears in inline
                            if cell_name in inline_names:
                                continue
                            participating_submodule_instance_names.append(cell_name)
                            participating_names.append(_strip_backslash(cell.name))
                else:
                    raise Exception(
                        f"{tactic.json_path}: No module, module instance, or assert found with name  {inst.name}"
                    )

            logger.debug(
                f"{parent_objective.top}: Generating assume-guarantee verification conditions"
            )
            logger.debug(
                f"\tParticipating submodule instances: {participating_submodule_instance_names}"
            )
            logger.debug(
                f"\tAll participating top asserts: {participating_assert_names}"
            )
            logger.debug(f"\tInlined: {inline_names}")

            if tactic.auto:
                depgraph = cg[parent_objective.top].get_module_dependency_graph(
                    set(participating_names)
                )
                logger.debug(f"\tInstance dependency relation:\n{depgraph}")
                if self.cfg.verbosity >= 2:
                    depgraph.write_module_dependencies_to_dot(
                        Path(
                            (
                                self.cfg.tmpdir
                                / (f"instance_deps_{parent_objective.top}.dot")
                            )
                        )
                    )
                ordered_instances = depgraph.get_topological_ordering()
            else:
                ordered_instances = list(
                    cg[parent_objective.top].top_module.cell(f"\\{name}")
                    for name in participating_names
                )

            logger.debug(
                f"\tAssume-guarantee order (auto: {tactic.auto}): {[inst.name for inst in ordered_instances]}"
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
                            f"{parent_objective.top}/{cell_name}.{inst_cell_name}.*"
                        )
                        exclude_list.extend(
                            [
                                f"{parent_objective.top}/$flatten\\{cell_name}.{inst_cell_name}.*",
                                f"{parent_objective.top}/$flatten\\{cell_name}.\\{inst_cell_name}.*",
                            ]
                        )
                    script.append(
                        f"setattr -set _ag_vc_flattened 1 {parent_objective.top}/{cell_name}.* {parent_objective.top}/$flatten\\{cell_name}.* %u {' %d '.join(exclude_list)} {'%d' if exclude_list else ''}"
                    )
                return script

            top_ag_task = self._get_task_or_group_name(f"_vc_{parent_task}_top")
            top_ag_script = [
                "chformal -remove -cover -live",
                "# Mark check cells at the top level:",
                f"setattr -set _ag_vc_top 1 {parent_objective.top}/* t:$check %i",
                "# Flatten cells participating to assume-guarantee:",
                "flatten "
                + " ".join(
                    [f"{parent_objective.top}/{s}" for s in participating_names]
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
                    "# Remove all assumptions of submodules and convert submodules' asserts into assumes",
                    "chformal -remove -assume a:_ag_vc_flattened=1",
                    "chformal -assert -assert2assume a:_ag_vc_flattened=1",
                ]
            )
            if participating_assert_names:
                top_ag_script.extend(
                    [
                        "# Also convert any top-level asserts among instances to assumes",
                        f"chformal -assert -assert2assume {' '.join([parent_objective.top + '/' + name for name in participating_assert_names])}",
                    ]
                )
            top_ag_script.extend(
                [
                    "log Remaining assumes for this VC:",
                    "select r:FLAVOR=assume -list",
                    "log Remaining asserts for this VC:",
                    "select r:FLAVOR=assert -list",
                ]
            )
            top_ag_script.append("opt_clean -purge")

            def _subcell_names_of_cell(cell) -> str:
                if cell.type == "$assert":
                    return f"{parent_objective.top}/{_strip_backslash(cell.name)}"
                else:
                    return f"{parent_objective.top}/{_strip_backslash(cell.name)}.* {parent_objective.top}/$flatten\\{_strip_backslash(cell.name)}.* %u"

            top_ag_script.extend(
                [
                    f"select -module {parent_objective.top}",
                    f"show -stretch -prefix {parent_objective.top} -format svg",
                ]
            )

            # TODO Process subtactics recursively
            self.script.append((top_ag_task, top_ag_script))
            self.add_task(top_ag_task, copy.copy(task_groups), [])

            previous_cells = []
            next_cells = copy.copy(ordered_instances)
            while next_cells:
                cell = next_cells.pop(0)
                cell_name = _strip_backslash(cell.name)
                inst_ag_task = self._get_task_or_group_name(
                    f"_vc_{parent_task}_{cell_name}_"
                )
                inst_ag_script = [
                    "chformal -remove -cover -live",
                    "# Remove all top-level asserts and flatten:",
                    f"chformal -assert -remove {parent_objective.top}/*",
                    "# Mark assume cells at the top level:",
                    f"setattr -set _ag_vc_top 1 {parent_objective.top}/* t:$check %i",
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
                        f"select -module {parent_objective.top}",
                        f"show -stretch -prefix {inst_ag_task} -format svg",
                    ]
                )

                # TODO Process subtactics recursively
                self.script.append((inst_ag_task, inst_ag_script))
                self.add_task(inst_ag_task, copy.copy(task_groups), [parent_task])

                previous_cells.append(cell)
        elif isinstance(tactic, parser.CutpointTactic):
            raise Exception("Not implemented")
        elif isinstance(tactic, parser.SplitTactic):
            raise Exception("Not implemented")
        else:
            raise Exception(f"Unknown tactic {type(tactic)}")

    def process_objective(
        self, objective: parser.Objective, proven_tops: set[str]
    ) -> list[parser.Objective]:
        """Generate tasks and subtasks for this objective, and return the list of objectives that appear in the subtree.

        Returns a list of further objectives to be processed.
        """
        logger.debug(f"Processing objective {objective.json_path:} {objective.top}")
        if objective.top in self._processed_modules:
            return []
        self._processed_modules.add(objective.top)

        new_objectives = []
        cg: dict[str, CellGraph] = cell_graph.get_cell_graphs(
            self.strategy.header,
            objective.top,
            self.strategy.multiclock,
            self.cfg,
        )

        main_common_task = self._get_task_or_group_name(f"_{objective.top}_common")
        objective_script = [line for line in self.strategy.header]
        objective_script.extend([f"hierarchy -top {objective.top}", "proc"])
        if objective.early_assert or objective.early_assume:
            objective_script.append(
                "chformal -early -assert "
                + ("-assume" if objective.early_assume else "")
            )
        self.script.append((main_common_task, objective_script))

        if objective.tactic is None:
            self.add_task(objective.top, [main_common_task])
        else:
            self.process_tactic(
                objective.tactic,
                objective.top,
                [],
                [main_common_task],
                cg,
                objective,
                proven_tops,
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
