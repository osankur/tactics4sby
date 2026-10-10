import copy
import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
import queue
import re

from logger import logger
import parser
import cell_graph
import configuration
from cell_graph import strip_backslash, ensure_backslash, CellGraph
from sby_script import SbyScript, VerificationCondition


@dataclass
class SbyGenerator:
    strategy: parser.ProofStrategy
    cfg: configuration.Configuration
    verbose: bool = False
    verbose_yosys: bool = False

    vcs: list[VerificationCondition] = field(default_factory=lambda: [])
    _goal_list: queue.Queue[parser.Goal] = field(
        default_factory=lambda: queue.Queue[parser.Goal]()
    )
    # set of module names that have been generated as goals
    _generated_module_goals: set[str] = field(default_factory=lambda: set())

    # task and group names used so far
    _task_and_group_names: set[str] = dataclasses.field(default_factory=set)

    def get_sby_script(self, sby_file) -> SbyScript:
        toplevel_options = list(self.strategy.options)
        if self.strategy.multiclock:
            toplevel_options.append("multiclock on")
        self._goal_list.put(self.strategy.goal)
        while not self._goal_list.empty():
            goal = self._goal_list.get()
            self.process_goal(goal)
        return SbyScript(
            toplevel_options,
            list(self.strategy.engines),
            [],
            list(self.strategy.files),
            self.vcs,
            sby_file,
            self.cfg,
        )

    def _get_task_or_group_name(self, name: str) -> str:
        counter = 0
        while name in self._task_and_group_names:
            name = f"{name}_{counter}"
            counter += 1
        self._task_and_group_names.add(name)
        return name

    def _schedule_goal(self, module_name: str) -> None:
        """
        Schedule the given module for VC generation.
        """
        module_name = ensure_backslash(module_name)
        if module_name in self._generated_module_goals:
            return
        # Clean the instantiated module names so that task names can be parsed by sby
        vc_name = module_name.replace("$", "_").replace("'", "_")
        self._generated_module_goals.add(module_name)
        for subgoal in self.strategy.subgoals:
            pat = rf"\$paramod{module_name}\\"
            if subgoal.module == module_name or re.match(pat, subgoal.module):
                self._goal_list.put(
                    parser.Goal(
                        module=module_name,
                        name=vc_name,
                        tactic=subgoal.tactic,
                        options=subgoal.options,
                        engines=subgoal.engines,
                    )
                )
                return
        self._goal_list.put(parser.Goal(module=module_name, name=vc_name))

    def process_tactic(
        self,
        tactic: parser.Tactic | None,
        vc_path: str,
        pre_script: list[str],
        cg: dict[str, CellGraph],
        parent_goal: parser.Goal,
    ) -> VerificationCondition | None:
        """
        Explore the tactic tree recursively returning a list of VerificationCondition objects which are premises of this tactic.
        """
        if tactic is None and pre_script == []:
            return None
        if isinstance(tactic, parser.NoneTactic) or tactic is None and pre_script:
            return VerificationCondition(
                vc_path,
                "",
                [],
                list(tactic.options) if tactic else [],
                list(tactic.engines) if tactic else [],
                pre_script,
            )
        if isinstance(tactic, parser.AssumeGuaranteeTactic):
            all_module_names = set(
                str(k) for k in cg[ensure_backslash(parent_goal.module)].design.modules_
            )
            user_defined_cells = list(
                filter(
                    lambda cell: str(cell.type) in all_module_names
                    or cell.type == "$assert",
                    cg[ensure_backslash(parent_goal.module)].top_module.cells_.values(),
                )
            )
            user_defined_cell_names = set(str(cell.name) for cell in user_defined_cells)
            user_defined_module_instance_cells = list(
                filter(lambda cell: cell.type != "$assert", user_defined_cells)
            )
            all_submodule_names = all_module_names & set(
                str(cell.type) for cell in user_defined_module_instance_cells
            )
            instances = (
                tuple(
                    parser.Instance(
                        name=ensure_backslash(inst.name),
                        tactic=inst.tactic,
                        json_path=inst.json_path,
                    )
                    for inst in tactic.instances
                )
                if tactic.instances
                else tuple(
                    parser.Instance(
                        name=name,
                        tactic=tactic.tactic,
                        json_path=f"{tactic.json_path}.{name}",
                    )
                    for name in all_submodule_names
                )
            )

            inline_names = set()
            if tactic.inline:
                assert tactic.auto
                inline_names = set(ensure_backslash(name) for name in tactic.inline)

            participating_assert_names = []
            participating_submodule_instance_names = []
            for inst in instances:
                if inst.name in user_defined_cell_names:
                    # the cell name appears in inline
                    if inst.name in inline_names:
                        continue
                    inst_cell = cg[
                        ensure_backslash(parent_goal.module)
                    ].top_module.cell(inst.name)
                    if inst_cell.type == "$assert":
                        participating_assert_names.append(inst.name)
                    else:
                        assert str(inst_cell.type) in all_submodule_names, (
                            f"{tactic.json_path}: {inst.name} (of type {inst_cell.type}) is neither a module instance or an assert"
                        )
                        participating_submodule_instance_names.append(inst.name)
                        self._schedule_goal(str(inst_cell.type))
                elif inst.name in all_submodule_names:
                    # the module name appears in inline
                    if inst.name in inline_names:
                        continue
                    for cell in user_defined_module_instance_cells:
                        if cell.type == inst.name:
                            cell_name = str(cell.name)
                            # the cell name appears in inline
                            if cell_name in inline_names:
                                continue
                            participating_submodule_instance_names.append(cell_name)
                            self._schedule_goal(str(cell.type))
                else:
                    raise Exception(
                        f"{tactic.json_path}: No module, module instance, or assert found with name  {inst.name}"
                    )
            participating_names = (
                participating_submodule_instance_names + participating_assert_names
            )

            logger.debug(
                f"{parent_goal.module}: Generating assume-guarantee verification conditions"
            )
            logger.debug(
                f"\tParticipating submodule instances: {participating_submodule_instance_names}"
            )
            logger.debug(
                f"\tAll participating top asserts: {participating_assert_names}"
            )
            logger.debug(f"\tInlined: {inline_names}")

            if tactic.auto:
                depgraph = cg[
                    ensure_backslash(parent_goal.module)
                ].get_module_dependency_graph(set(participating_names))
                logger.debug(f"\tInstance dependency relation:\n{depgraph}")
                if self.cfg.verbosity >= 2:
                    depgraph.write_module_dependencies_to_dot(
                        Path(
                            (
                                self.cfg.tmpdir
                                / (f"instance_deps_{parent_goal.module}.dot")
                            )
                        )
                    )
                ordered_instances = depgraph.get_topological_ordering()
            else:
                ordered_instances = list(
                    cg[ensure_backslash(parent_goal.module)].top_module.cell(name)
                    for name in participating_names
                )

            logger.debug(
                f"\tAssume-guarantee order (auto: {tactic.auto}): {[str(inst.name) for inst in ordered_instances]}"
            )

            def _mark_level1_child_check_cells(cells, attribute: str) -> list[str]:
                """Set given attribute to all objects of submodules that appear among cells,
                but not to the objects of their subsubmodules.
                """
                script = []
                for cell in cells:
                    exclude_list = []
                    if cell.type == "$assert":
                        continue
                    submodule_name = str(cell.type)
                    cell_name = str(cell.name)
                    for inst_cell in cg[submodule_name].submodule_instance_cells:
                        inst_cell_name = str(inst_cell.name)
                        exclude_list.append(
                            f"{parent_goal.module}/{cell_name}.{inst_cell_name}.*"
                        )
                        exclude_list.extend(
                            [
                                f"{parent_goal.module}/$flatten{cell_name}.{inst_cell_name}.*",
                                f"{parent_goal.module}/$flatten{cell_name}.{strip_backslash(inst_cell_name)}.*",
                            ]
                        )
                    script.append(
                        f"setattr -set {attribute} 1 {parent_goal.module}/{cell_name}.* {parent_goal.module}/$flatten{cell_name}.* %u {' %d '.join(exclude_list)} {'%d' if exclude_list else ''}"
                    )
                return script

            top_ag_script = [
                "# Mark check cells at the top level:",
                f"setattr -set _ag_vc_top 1 {parent_goal.module}/* t:$check %i",
                "# Flatten cells participating to assume-guarantee:",
                "flatten "
                + " ".join([f"{parent_goal.module}/{s}" for s in participating_names]),
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
                        f"chformal -assert -assert2assume {' '.join([parent_goal.module + '/' + name for name in participating_assert_names])}",
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

            def _subcell_names_of_cell(cell) -> str:
                if cell.type == "$assert":
                    return f"{parent_goal.module}/{cell.name}"
                else:
                    return f"{parent_goal.module}/{cell.name}.* {parent_goal.module}/$flatten{cell.name}.* %u"

            if self.cfg.dump_dot_circuits:
                top_ag_script.extend(
                    [
                        f"select -module {parent_goal.module}",
                        f"show -stretch -prefix {parent_goal.module} -format svg",
                        "select -clear",
                    ]
                )
            child_vc = self.process_tactic(
                tactic.tactic,
                self._get_task_or_group_name(f"{vc_path}_ag_top"),
                top_ag_script,
                cg,
                parent_goal,
            )
            assert child_vc
            vcs = [child_vc]

            previous_cells = []
            next_cells = copy.copy(ordered_instances)
            while next_cells:
                cell = next_cells.pop(0)
                cell_name = str(cell.name)

                inst_ag_task = self._get_task_or_group_name(
                    f"{vc_path}_ag_{strip_backslash(cell_name)}"
                )
                inst_ag_script = [
                    "# Remove all top-level asserts and flatten:",
                    f"chformal -assert -remove {parent_goal.module}/*",
                    "# Mark assume cells at the top level:",
                    f"setattr -set _ag_vc_top 1 {parent_goal.module}/* t:$check %i",
                    "flatten",
                ]

                inst_ag_script.extend(
                    _mark_level1_child_check_cells(
                        ordered_instances, "_ag_vc_flattened"
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
                    ]
                )
                if self.cfg.dump_dot_circuits:
                    inst_ag_script.extend(
                        [
                            f"select -module {parent_goal.module}",
                            f"show -stretch -prefix {inst_ag_task} -format svg",
                            "select -clear",
                        ]
                    )
                subvc = self.process_tactic(
                    inst.tactic if inst else None,
                    inst_ag_task,
                    inst_ag_script,
                    cg,
                    parent_goal,
                )
                assert subvc
                vcs.append(subvc)
                previous_cells.append(cell)
            return VerificationCondition(
                vc_path,
                f"{tactic.__class__.__name__}",
                vcs,
                list(tactic.options),
                list(tactic.engines),
                pre_script,
            )
        elif isinstance(tactic, parser.CutpointTactic):
            # from local wire names to global wire names
            selection = " ".join(
                map(
                    lambda name: f"{parent_goal.module}/{name}",
                    tactic.selection.split(" "),
                )
            )
            child_tactic = self.process_tactic(
                tactic.tactic,
                f"{vc_path}_cp",
                [
                    f"select {selection} -assert-any",
                    f"cutpoint {selection}",
                ],
                cg,
                parent_goal,
            )
            return VerificationCondition(
                vc_path,
                tactic.__class__.__name__,
                [child_tactic] if child_tactic else [],
                list(tactic.options),
                list(tactic.engines),
                pre_script,
            )
        elif isinstance(tactic, parser.SplitTactic):
            if (
                f"\\{tactic.split_wire}"
                not in cg[ensure_backslash(parent_goal.module)].top_module.wires_
            ):
                raise Exception(
                    f"{tactic.json_path}: Could not find wire {tactic.split_wire!r} in module {parent_goal.module!r}"
                )
            split_wire = cg[ensure_backslash(parent_goal.module)].top_module.wires_[
                f"\\{tactic.split_wire}"
            ]
            if split_wire.width != 1:
                raise Exception(
                    f"{tactic.json_path}: The width of the split_wire {tactic.split_wire!r} is not 1."
                )
            # Child VCs must be non-empty since we need to add preamble to their scripts to assume the case condition
            # so we replace any tactic that is None by an instance of NoneTactic()
            child0 = self.process_tactic(
                tactic.case_false if tactic.case_false else parser.NoneTactic(),
                f"{vc_path}_split0",
                [
                    f"select -module {parent_goal.module}",
                    f"add -assume {tactic.split_wire} -not",
                    "select -clear",
                ],
                cg,
                parent_goal,
            )
            assert child0

            child1 = self.process_tactic(
                tactic.case_true if tactic.case_true else parser.NoneTactic(),
                f"{vc_path}_split1",
                [
                    f"select -module {parent_goal.module}",
                    f"add -assume {tactic.split_wire}",
                    "select -clear",
                ],
                cg,
                parent_goal,
            )
            assert child1
            return VerificationCondition(
                vc_path,
                tactic.__class__.__name__,
                [child0, child1],
                list(tactic.options),
                list(tactic.engines),
                pre_script,
            )
        else:
            raise Exception(f"Unknown tactic {type(tactic)}")

    def process_goal(self, goal: parser.Goal):
        logger.debug(f"Processing goal {goal.json_path:} {goal.module}")

        cg: dict[str, CellGraph] = cell_graph.get_cell_graphs(
            self.strategy.header,
            goal.module,
            self.strategy.multiclock,
            self.cfg,
        )

        goal_script = [line for line in self.strategy.header]
        goal_script.extend(
            [
                f"hierarchy -top {self.strategy.goal.module}",
                "proc",
                "chformal -remove -cover -live",
            ]
        )
        if self.strategy.early_assert or self.strategy.early_assume:
            goal_script.append(
                "chformal -early -assert "
                + ("-assume" if self.strategy.early_assume else "")
            )
        if goal.name:
            vc_path = self._get_task_or_group_name(goal.name)
        else:
            vc_path = self._get_task_or_group_name(goal.module)
        vc = self.process_tactic(goal.tactic, vc_path, goal_script, cg, goal)
        assert vc
        self.vcs.append(vc)
