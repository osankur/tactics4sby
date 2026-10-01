import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Configuration:
    basedir: Path
    verbosity: int
    tmpdir: Path = field(default_factory=lambda: Path(tempfile.gettempdir()))
    verbose_yosys: bool = False
    verbose_sby: bool = False
    dump_ag_dependency_graph: bool = False
    dump_dot_circuits: bool = False
