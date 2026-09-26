import copy
from dataclasses import dataclass
from logger import logger
from collections import deque
import proof_strategy
import cell_graph

def _strip_backslash(id):
    assert id[0] == "\\"
    return str(id)[1:]

@dataclass
class SbyTask:
    name : str
    groups : list[str]

@dataclass
class SbyScript:
    name : str
    strategy : proof_strategy.ProofStrategy
    verbose : bool = False

    DEFAULT_OPTION = "mode prove"
    DEFAULT_ENGINE = "smtbmc"

    tasks : list[SbyTask] = []
    options : dict[str,str] = {}
    engine : dict[str,str] = {}
    script : list[tuple[str,list[str]]] = []
    
    # module contract proofs that have already been generated:
    _processed_modules : set[str] = set()

    def _remove_noncontract_check_cells(self, top : str, assertions : tuple[str,...] | None, assumptions : tuple[str,...] | None, cg : dict[str,cell_graph.CellGraph]) -> list[str]:
        """ Given assertions and assumptions lists, remove other check cells for module ``top``.
            If one of these lists is None, then keep all the check cells.
        """
        script = []
        assert_cell_names = { c.name for c in cg[top].assert_cells }
        assume_cell_names = { c.name for c in cg[top].assume_cells }    
        if assertions:
            for cell_name in assertions:
                if f"\\{cell_name}" not in assert_cell_names:
                    raise Exception(f"objective.path: assertion {cell_name} not found in module {top}")
            # Remove all deselected assertions
            script.append(f"select t:$check {top}* %i r:FLAVOR=assert %i")
            script.append(f"select -del {" ".join(assertions)}")
            script.append("tee -a logs.txt Removing following assert cells")
            script.append("select -list")
            script.append("delete")
        if assumptions:
            # Remove all deselected assumes
            for cell_name in assumptions:
                if f"\\{cell_name}" not in assume_cell_names:
                    raise Exception(f"objective.path: assume {cell_name} not found in module {top}")
            script.append(f"select t:$check {top}* %i r:FLAVOR=assume %i")
            script.append(f"select -del {" ".join(assumptions)}")
            script.append("tee -a logs.txt Removing following assume cells")
            script.append("select -list")
            script.append("delete")
        return script

    def process_objective(self, objective : proof_strategy.Objective) -> list[proof_strategy.Objective]:
        """ Generate tasks and subtasks for this objective, and return the list of objectives that appear in the subtree.
        
            Groups generated for the assume_guarantee tactic:
            - objective_group: remove all submodule instances (except those inlined) by applying cutpoint on their outputs
            - top_ag_group: flatten, then remove submodule assumptions, and convert their assertions into assumptions
                            then prove the top module's contract
            - inst_ag_common_group: remove all asserts of top module, then flatten
            - inst_ag_group(*): focus on one instance; remove all other instances' assumptions, assume previous instances assertions,
                                and remove next instances assertions; prove the current instance assumption
            
            Added tasks are:
            - top_ag_group objective_group
            and for each instance `s`
            - /inst_ag_group`s` objective_group inst_ag_common_group        
        """
        if objective.top in self._processed_modules:
            return []
        self._processed_modules.add(objective.top)

        new_objectives = []
        cg = cell_graph.get_cell_graphs(self.strategy.header, objective.top, self.strategy.multiclock)

        objective_group = f"f{objective.json_path}_top"
        objective_script = [line for line in self.strategy.header]
        objective_script.append(f"hierarchy -top {objective.top}")

        if objective.early_assert or objective.early_assume:
            objective_script.append("chformal -early -assert " + ("-assume" if objective.early_assume else ""))

        if objective.tactic is None:
            logger.info(f"{objective.top}: Generating direct task")
            self.script.append((objective_group,objective_script))
            self.tasks.append(SbyTask(objective_group, []))
        elif isinstance(objective.tactic, proof_strategy.AssumeGuaranteeTactic):

            inlined_instances = [] if objective.tactic.instances is None else [inst.name for inst in objective.tactic.instances if inst.inline]
            all_modules = set(str(_strip_backslash(k)) for k in cg[objective.top].topmodule.design.modules_.keys())
            all_submodules = all_modules & set(_strip_backslash(cell.type) for cell in cg[objective.top].topmodule.cells_.values())
            participating_submodules = all_submodules if objective.tactic.submodules is None else objective.tactic.submodules.keys()
            if not set(participating_submodules).issubset(all_submodules):
                raise Exception(f"{objective.tactic.json_path}: Following modules do not appear inside module {objective.top}: {participating_submodules - all_submodules}")
            
            for inst in objective.tactic.instances:
                if f"\\{inst.name}" not in cg[objective.top].topmodule.cells_.keys():
                    raise Exception(f"{objective.tactic.json_path}: no instance {inst.name} found in module {objective.top}")
                if not inst.inline and inst.tactic is not None:
                    raise Exception(f"{inst.json_path}: nested tactics are currently not allowed.")

            participating_instances = []
            for (cell_name, cell) in cg[objective.top].topmodule.cells_.items():
                cell_name = _strip_backslash(cell_name)
                cell_type = _strip_backslash(cell.type)
                if cell_type in all_submodules and cell_type not in participating_submodules:
                    inlined_instances.append(cell_name)
                else:
                    participating_instances.append(cell_name)

            logger.debug(f"{objective.top}: Generating assume-guarantee verification conditions")
            logger.debug(f"\tFollowing submodules participate in assume-guarantee decomposition: {participating_submodules}")
            logger.debug(f"\tFollowing instances are inlined: {inlined_instances}")
            logger.debug(f"\tFollowing instances participate in assume-guarantee decomposition: {participating_instances}")

            ordered_instances= cg[objective.top].get_module_dependency_graph(set(participating_instances)).get_topological_ordering()
            # TODO if the order is user specified, consider the order, and do not compute topological ordering
            logger.debug(f"Submodule instances order: {[inst.name for inst in ordered_instances]}")
            for cell in ordered_instances:
                cell_name = _strip_backslash(cell.name)
                # Do not cut if to be inlined
                if _strip_backslash(cell.name) in inlined_instances:
                    continue
                # Cut all outputs of the cell
                for (conn_name, _) in cell.connections_:
                    if cell.output(conn_name):
                        objective_script.append(f"cutpoint {objective.top}/{_strip_backslash(cell.name)}.{conn_name}")
                objective_script.append("opt_clean -purge")

            self.script.append((objective_group,objective_script))

            top_ag_group = objective_group + "_ag_top_"
            top_ag_script = ["proc", "flatten"]
            for cell in ordered_instances:
                cell_name = _strip_backslash(cell.name)                
                # Convert instance's asserts into assumes
                top_ag_script.append(f"chformal -remove -assume {objective.top}/{cell_name}.*")
                top_ag_script.append(f"chformal -assert -assert2assume {objective.top}/{cell_name}.*")
            self.script.append((top_ag_group,top_ag_script))
            # Task: disconnect submodules (objective_group), and prove the top contract
            self.tasks.append(SbyTask(top_ag_group, [objective_group]))

            # Group common to all subinstance VCs
            inst_ag_common_group = objective_group + "_ag_inst_common_"
            # remove the main assertions, and flatten
            inst_ag_common_script = ["proc", "chformal -assert -remove", "flatten"]
            # remove all submodule instances' assumptions
            for cell in ordered_instances:
                cell_name = _strip_backslash(cell.name)
                inst_ag_common_script.append(f"chformal -assume -remove {objective.top}/{cell_name}.*")
            self.script.append((inst_ag_common_group,inst_ag_common_script))

            previous_cell_names = []
            next_cells = copy.copy(ordered_instances)
            while next_cells:
                cell = next_cells.pop(0)
                cell_name = _strip_backslash(cell.name)
                inst_ag_group = objective_group + f"_ag_{cell_name}_"
                inst_ag_script = []
                # assume previous instances' assertions
                for prev_cell in previous_cell_names:
                    inst_ag_script.append(f"chformal -assert -assert2assume {objective.top}/{prev_cell}.*")
                # remove next cells' assertions
                for next_cell in next_cells:
                    inst_ag_script.append(f"chformal -assert -remove {objective.top}/{_strip_backslash(next_cell.name)}.*")
                # prove current cell's assumptions
                inst_ag_script.append(f"chformal -assume -assume2assert {objective.top}/{cell_name}.*")
                self.script.append((inst_ag_group,inst_ag_script))
                self.tasks.append(SbyTask(inst_ag_group, [objective_group, inst_ag_common_group]))
            if objective.tactic.submodules:
                for subm in objective.tactic.submodules.values():
                    new_objectives.append(subm)
        else:
            raise Exception(f"{objective.tactic.json_path} only assume-guarantee tactic is supported currently")
        return new_objectives

def process_objectives(self, objectives: list[proof_strategy.Objective]):
    objective_queue = deque(objectives)
    while objective_queue:
        obj = objective_queue.popleft()
        objective_queue.extend(self.process_objective(obj))
    
    def generate_sby(self, proof_strategy : proof_strategy.ProofStrategy):
        
        pass
