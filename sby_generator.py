import sys
from typing import TextIO
import copy
import dataclasses
from dataclasses import dataclass
from logger import logger
from collections import deque
import proof_strategy
import cell_graph
from cell_graph import _strip_backslash


@dataclass
class SbyTask:
    name: str
    groups: list[str]


@dataclass
class SbyScript:
    strategy: proof_strategy.ProofStrategy
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

    def _remove_noncontract_check_cells(
        self,
        top: str,
        assertions: tuple[str, ...] | None,
        assumptions: tuple[str, ...] | None,
        cg: dict[str, cell_graph.CellGraph],
    ) -> list[str]:
        """Given assertions and assumptions lists, remove other check cells for module ``top``.
        If one of these lists is None, then keep all the check cells.
        """
        script = []
        assert_cell_names = {c.name for c in cg[top].assert_cells}
        assume_cell_names = {c.name for c in cg[top].assume_cells}
        if assertions:
            for cell_name in assertions:
                if f"\\{cell_name}" not in assert_cell_names:
                    raise Exception(
                        f"objective.path: assertion {cell_name} not found in module {top}"
                    )
            # Remove all deselected assertions
            script.append(f"select t:$check {top}* %i r:FLAVOR=assert %i")
            script.append(f"select -del {' '.join(assertions)}")
            script.append("tee -a logs.txt Removing following assert cells")
            script.append("select -list")
            script.append("delete")
        if assumptions:
            # Remove all deselected assumes
            for cell_name in assumptions:
                if f"\\{cell_name}" not in assume_cell_names:
                    raise Exception(
                        f"objective.path: assume {cell_name} not found in module {top}"
                    )
            script.append(f"select t:$check {top}* %i r:FLAVOR=assume %i")
            script.append(f"select -del {' '.join(assumptions)}")
            script.append("tee -a logs.txt Removing following assume cells")
            script.append("select -list")
            script.append("delete")
        return script

    def process_objective(
        self, objective: proof_strategy.Objective
    ) -> list[proof_strategy.Objective]:
        """Generate tasks and subtasks for this objective, and return the list of objectives that appear in the subtree.

        Groups generated for the assume_guarantee tactic:
        - ``top``               : remove all submodule instances (except those inlined) by applying cutpoint on their outputs
        - _vc_``top``_top       : flatten, then remove submodule assumptions, and convert their assertions into assumptions
                                  then prove the top module's contract
        - _vc_``top``_common    : remove all asserts of top module, then flatten
        - _vc_``top``_``inst``  : focus on one instance; remove all other instances' assumptions, assume previous instances assertions,
                                  and remove next instances assertions; prove the current instance assumption

        Returns a list of further objectives to be processed.
        """
        logger.debug(f"Visiting objective {objective.json_path:} {objective.top}")
        if objective.top in self._processed_modules:
            return []
        self._processed_modules.add(objective.top)

        new_objectives = []
        cg = cell_graph.get_cell_graphs(
            self.strategy.header,
            objective.top,
            self.strategy.multiclock,
            self.verbose_yosys,
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
            logger.info(f"{objective.top}: Generating direct task")
            self.add_task(main_task, [])
        elif isinstance(objective.tactic, proof_strategy.AssumeGuaranteeTactic):
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
                    f"Following modules do not appear inside module {objective.top}: {all_submodule_names.difference(set(objective.tactic.submodules.keys()))}"
                )
            participating_submodule_names = (
                all_submodule_names
                if objective.tactic.submodules is None
                else set(objective.tactic.submodules.keys())
            )
            if not set(participating_submodule_names).issubset(all_submodule_names):
                raise Exception(
                    f"{objective.tactic.json_path}: Following modules do not appear inside module {objective.top}: {participating_submodule_names - all_submodule_names}"
                )

            if objective.tactic.instances:
                user_defined_cell_names = set(
                    str(cell.name) for cell in user_defined_cells
                )
                print(user_defined_cell_names)
                for inst in objective.tactic.instances:
                    if f"\\{inst}" not in user_defined_cell_names:
                        raise Exception(
                            f"{objective.tactic.json_path}: no instance {inst} found in module {objective.top})"
                        )

            # instances whose modules appear in participating_submodules
            participating_submodule_instances: set[str] = set()
            for cell in user_defined_cells:
                if cell.type[0] == "\\":
                    cell_type = _strip_backslash(cell.type)
                    if cell_type in participating_submodule_names:
                        participating_submodule_instances.add(
                            _strip_backslash(cell.name)
                        )

            if objective.tactic.instances:
                participating_instances = tuple(objective.tactic.instances)
                inlined_instances = tuple(
                    participating_submodule_instances - set(participating_instances)
                )
            elif objective.tactic.inline:
                assert objective.tactic.auto
                inlined_instances = tuple(objective.tactic.inline)
                participating_instances = tuple(
                    participating_submodule_instances - set(inlined_instances)
                )
            else:
                inlined_instances = []
                participating_instances = participating_submodule_instances

            logger.debug(
                f"{objective.top}: Generating assume-guarantee verification conditions"
            )
            logger.debug(
                f"\tFollowing submodules participate in assume-guarantee decomposition: {participating_submodule_names}"
            )
            logger.debug(
                f"\tAll instances of the participating submodules: {participating_submodule_instances}"
            )
            logger.debug(f"\tInlined: {inlined_instances}")
            logger.debug(f"\tDecomposed: {participating_instances}")

            if objective.tactic.auto:
                ordered_instances = (
                    cg[objective.top]
                    .get_module_dependency_graph(set(participating_instances))
                    .get_topological_ordering()
                )
            else:
                ordered_instances = list(
                    cg[objective.top].top_module.cell(f"\\{name}")
                    for name in participating_instances
                )
            logger.debug(
                f"\tAssume-guarantee order (auto: {objective.tactic.auto}): {[inst.name for inst in ordered_instances]}"
            )

            top_ag_task = self._get_task_or_group_name(f"_vc_{main_task}_top")
            top_ag_script = ["flatten"]
            for cell in ordered_instances:
                cell_name = _strip_backslash(cell.name)
                # Do not cut if to be inlined
                if _strip_backslash(cell.name) in inlined_instances:
                    continue
                # Ignore if assert cell
                if cell.type == "$assert":
                    continue
                # Cut all outputs of the cell
                for conn_name in cell.connections_:
                    if cell.output(conn_name):
                        top_ag_script.append(
                            f"cutpoint {objective.top}/{_strip_backslash(cell.name)}.{_strip_backslash(conn_name)}"
                        )
            top_ag_script.append("opt_clean -purge")

            def _assumes_and_asserts_of_cell(cell) -> str:
                if cell.type == "$assert":
                    return f"{objective.top}/{_strip_backslash(cell.name)}"
                else:
                    return f"{objective.top}/{_strip_backslash(cell.name)}.*"

            for cell in ordered_instances:
                cell_name = _strip_backslash(cell.name)
                if cell.type == "$assert":
                    # Convert to assume
                    top_ag_script.append(
                        f"chformal -remove -assume {_assumes_and_asserts_of_cell(cell)}"
                    )
                else:
                    # This is an module instance. Convert instance's all asserts into assumes
                    top_ag_script.append(
                        f"chformal -remove -assume {_assumes_and_asserts_of_cell(cell)}"
                    )
                    top_ag_script.append(
                        f"chformal -assert -assert2assume {_assumes_and_asserts_of_cell(cell)}"
                    )
            self.script.append((top_ag_task, top_ag_script))
            # Task: disconnect submodules first (main_task), then prove the top contract
            self.add_task(main_task, [top_ag_task], [])

            # Group common to all subinstance VCs
            inst_ag_common_group = self._get_task_or_group_name(
                f"_vc_{main_task}_common"
            )
            # remove all top-level assertions, then flatten
            inst_ag_common_script = ["chformal -assert -remove", "flatten"]
            # # remove all submodule instances' assertions; leaving only toplevel and submodule assumptions
            # for cell in ordered_instances:
            #     cell_name = _strip_backslash(cell.name)
            #     inst_ag_common_script.append(
            #         f"chformal -assert -remove {_assumes_and_asserts_of_cell(cell)}"
            #     )
            self.script.append((inst_ag_common_group, inst_ag_common_script))

            previous_cells = []
            next_cells = copy.copy(ordered_instances)
            while next_cells:
                cell = next_cells.pop(0)
                cell_name = _strip_backslash(cell.name)
                inst_ag_task = self._get_task_or_group_name(
                    f"_vc_{main_task}_{cell_name}_"
                )
                inst_ag_script = []

                # remove previous instances' assumptions, and assume their assertions
                for prev_cell in previous_cells:
                    inst_ag_script.extend(
                        [
                            f"chformal -assume -remove {_assumes_and_asserts_of_cell(prev_cell)}",
                            f"chformal -assert -assert2assume {_assumes_and_asserts_of_cell(prev_cell)}",
                        ]
                    )
                # prove current cell's assumptions
                inst_ag_script.append(
                    f"chformal -assume -assume2assert {_assumes_and_asserts_of_cell(cell)} # vc goal"
                )
                # remove next cells' assumptions and assertions
                for next_cell in next_cells:
                    inst_ag_script.append(
                        f"chformal -assert -assume -remove {_assumes_and_asserts_of_cell(next_cell)}"
                    )
                self.script.append((inst_ag_task, inst_ag_script))
                self.add_task(
                    inst_ag_task, [main_task, inst_ag_common_group], [main_task]
                )
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
        print("[engine]", file=f)
        _dump_dict(self.engine, f)
        print("[script]", file=f)
        for group, content in self.script:
            print(f"{group}:", file=f)
            print("\n".join(content), file=f)
            print("--", file=f)
        print("[files]", file=f)
        print("\n".join(self.strategy.files), file=f)
