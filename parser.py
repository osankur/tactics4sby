"""Data model and parser for proof strategy JSON files."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, NoReturn

from logger import logger

__all__ = [
    "ProofStrategyError",
    "Tactic",
    "AssumeGuaranteeTactic",
    "SplitTactic",
    "Objective",
    "ProofStrategy",
    "parse_file",
    "parse_string",
    "parse_dict",
]


@dataclass(frozen=True)
class ModuleContract:
    """An assume-guarantee contract. ``asserts`` must be a subset of assertions, and ``assumes`` a subset of assumes in the given module."""

    asserts: list[str] | None = None
    assumes: list[str] | None = None


class ProofStrategyError(ValueError):
    """A proof strategy file is malformed.

    The message is prefixed with the JSON path of the offending value.
    """


TACTIC_NAMES: tuple[str, ...] = ("assume_guarantee", "split")


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Tactic:
    """Base class for the tactics an objective or VC can be decomposed with.

    ``name`` is the string that selects this tactic in the JSON file.
    ``json_path`` records where this object was parsed from and is excluded
    from comparison/hashing.
    """

    name: ClassVar[str]
    json_path: str = field(default="", compare=False)


@dataclass(frozen=True, kw_only=True)
class AssumeGuaranteeTactic(Tactic):
    """Acyclic assume-guarantee decomposition.

    ``submodules`` is ``None`` when the field is absent, meaning "consider all
    modules instantiated in the current top module"; otherwise a non-empty
    dict keyed by submodule name (the objective's ``top``, pairwise distinct),
    each value an :class:`Objective` -- each submodule is proven as a top
    module in its own right.

    ``auto`` selects how the instances are ordered.  When true (the default)
    the order is computed automatically, ``instances`` (if given) restricts
    which instances take part, and ``inline`` names the instances to inline.
    When false ``instances`` gives the order explicitly and every instance not
    listed is inlined.

    ``instances`` is ``None`` when the field is absent.  In manual mode
    (``auto`` false) it is required, so it is never ``None`` there.
    """

    submodules: dict[str, Objective] | None = None
    auto: bool = True
    instances: tuple[str, ...] | None = None
    inline: tuple[str, ...] = ()

    name: ClassVar[str] = "assume_guarantee"


@dataclass(frozen=True, kw_only=True)
class SplitTactic(Tactic):
    """Case split on a Verilog expression.

    ``case_false`` / ``case_true`` are the tactics applied to the branch where
    ``split_expression`` is false / true; ``None`` means that branch is proven
    directly.  The expression is evaluated in the module owning the VC.
    """

    split_expression: str
    case_false: Tactic | None = None
    case_true: Tactic | None = None

    name: ClassVar[str] = "split"


@dataclass(frozen=True, kw_only=True)
class Objective:
    """A single verification objective.

    ``name`` is an optional user-supplied label identifying the objective (for
    logs and error messages); it has no semantic effect.

    The contract of the objective's ``top`` module is *all* of its assertions
    and assumptions; there is no way to select a subset.  ``tactic`` is
    ``None`` for a leaf objective, proven directly.

    ``early_assume`` / ``early_assert`` are only settable on a top-level
    objective; nested objectives (a submodule's contract, or an objective
    reached through a tactic) inherit the values of the top-level objective
    they belong to.
    """

    top: str
    name: str | None = None
    early_assume: bool = False
    early_assert: bool = False
    tactic: Tactic | None = None
    json_path: str = field(default="", compare=False)


@dataclass(frozen=True, kw_only=True)
class ProofStrategy:
    """A parsed proof strategy: the top-level document.

    ``header`` lists the Yosys commands run once, in order, before any
    objective.  ``files`` is a tuple of source files to be considered in the sby configuration scripts.
    ``source`` records where the strategy was read from and is excluded from comparison/hashing.
    """

    header: tuple[str, ...]
    files: tuple[str, ...]
    objectives: tuple[Objective, ...]
    source: Path | None = field(default=None, compare=False)
    json_path: str = field(default="", compare=False)
    multiclock: bool = False


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #

_OBJECTIVE_REQUIRED = ("top",)
_OBJECTIVE_OPTIONAL = (
    "name",
    "early-assume",
    "early-assert",
    "tactic",
)
#: Nested objectives (submodule contracts) may not set the early flags: they
#: are inherited from the top-level objective.
_NESTED_OBJECTIVE_OPTIONAL = ("name", "tactic")
_PROOF_STRATEGY_REQUIRED = ("header", "files", "objectives")
_PROOF_STRATEGY_OPTIONAL = ()
_TOP_REQUIRED = ("proof_strategy",)
_TOP_OPTIONAL = ("$schema",)

#: Per tactic name: the keys it requires, and the keys it additionally tolerates.
#: 'name' is required by every tactic and is listed in the required tuple.
_TACTIC_KEYS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "assume_guarantee": (("name",), ("submodules", "auto", "instances", "inline")),
    "split": (("name", "split_expression"), ("case_false", "case_true")),
}


class _Parser:
    """Recursive-descent parser for proof strategy documents.

    Every error message is prefixed with the JSON path of the offending value.
    """

    # -- helpers ----------------------------------------------------------- #

    def _err(self, path: str, message: str) -> NoReturn:
        raise ProofStrategyError(f"{path}: {message}")

    def _object(self, value: Any, path: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            self._err(path, f"expected an object, got {type(value)}")
        return value

    def _check_keys(
        self,
        obj: dict[str, Any],
        path: str,
        required: tuple[str, ...],
        optional: tuple[str, ...],
    ) -> None:
        unknown = sorted(set(obj) - set(required) - set(optional))
        if unknown:
            allowed = sorted(set(required) | set(optional))
            self._err(
                path,
                "unknown key(s): "
                + ", ".join(f"'{key}'" for key in unknown)
                + "; allowed: "
                + ", ".join(f"'{key}'" for key in allowed),
            )
        missing = [key for key in required if key not in obj]
        if missing:
            self._err(
                path,
                "missing required key(s): " + ", ".join(f"'{key}'" for key in missing),
            )

    def _string(self, value: Any, path: str, *, allow_empty: bool = False) -> str:
        if not isinstance(value, str):
            self._err(path, f"expected a string, got {type(value)}")
        if not allow_empty and not value.strip():
            self._err(path, "must not be empty")
        return value

    def _bool(self, value: Any, path: str) -> bool:
        if not isinstance(value, bool):
            self._err(path, f"expected a boolean, got {type(value)}")
        return value

    def _string_list(
        self, value: Any, path: str, *, allow_empty: bool = True
    ) -> tuple[str, ...]:
        if not isinstance(value, list):
            self._err(path, f"expected an array of strings, got {type(value)}")
        items = tuple(
            self._string(item, f"{path}[{index}]") for index, item in enumerate(value)
        )
        if not allow_empty and not items:
            self._err(path, "must not be an empty array")
        return items

    def _check_distinct(self, names: list[str], path: str, what: str) -> None:
        seen: set[str] = set()
        for name in names:
            if name in seen:
                self._err(path, f"duplicate {what} name {name!r}")
            seen.add(name)

    # -- grammar ----------------------------------------------------------- #

    def top_level_objective(self, value: Any, path: str) -> Objective:
        """Parse an objective from ``proof_strategy.objectives``.

        Only these objectives may set ``early-assume`` / ``early-assert``;
        the values are then inherited by every nested objective below them.
        """
        obj = self._object(value, path)
        self._check_keys(obj, path, _OBJECTIVE_REQUIRED, _OBJECTIVE_OPTIONAL)

        early_assume = (
            self._bool(obj["early-assume"], f"{path}.early-assume")
            if "early-assume" in obj
            else False
        )
        early_assert = (
            self._bool(obj["early-assert"], f"{path}.early-assert")
            if "early-assert" in obj
            else False
        )
        if early_assume and not early_assert:
            self._err(path, "'early-assume' requires 'early-assert' to be true")

        return self._objective_body(
            obj, path, early_assume=early_assume, early_assert=early_assert
        )

    def nested_objective(
        self, value: Any, path: str, *, early_assume: bool, early_assert: bool
    ) -> Objective:
        """Parse an objective below a top-level one: early flags are inherited
        and must not be given."""
        obj = self._object(value, path)
        for key in ("early-assume", "early-assert"):
            if key in obj:
                self._err(
                    f"{path}.{key}",
                    f"'{key}' may only be set on a top-level objective; "
                    "nested objectives inherit it",
                )
        self._check_keys(obj, path, _OBJECTIVE_REQUIRED, _NESTED_OBJECTIVE_OPTIONAL)
        return self._objective_body(
            obj, path, early_assume=early_assume, early_assert=early_assert
        )

    def _objective_body(
        self,
        obj: dict[str, Any],
        path: str,
        *,
        early_assume: bool,
        early_assert: bool,
    ) -> Objective:
        top = self._string(obj["top"], f"{path}.top")
        name = (
            self._string(obj["name"], f"{path}.name")
            if obj.get("name") is not None
            else None
        )

        tactic: Tactic | None = None
        if obj.get("tactic") is not None:
            tactic = self.tactic(
                obj["tactic"],
                f"{path}.tactic",
                early_assume=early_assume,
                early_assert=early_assert,
            )

        return Objective(
            top=top,
            name=name,
            early_assume=early_assume,
            early_assert=early_assert,
            tactic=tactic,
            json_path=path,
        )

    def tactic(
        self,
        value: Any,
        path: str,
        *,
        early_assume: bool = False,
        early_assert: bool = False,
    ) -> Tactic:
        obj = self._object(value, path)
        if "name" not in obj:
            self._err(path, "missing required key: 'name'")
        name = self._string(obj["name"], f"{path}.name")
        if name not in _TACTIC_KEYS:
            self._err(
                f"{path}.name",
                f"unknown tactic {name!r}; expected one of "
                + ", ".join(repr(known) for known in TACTIC_NAMES),
            )
        required, optional = _TACTIC_KEYS[name]
        self._check_keys(obj, path, required, optional)

        if name == "assume_guarantee":
            return self._assume_guarantee(
                obj, path, early_assume=early_assume, early_assert=early_assert
            )

        # name == "split"
        expression = self._string(obj["split_expression"], f"{path}.split_expression")
        case_false = self._optional_case(
            obj,
            "case_false",
            path,
            early_assume=early_assume,
            early_assert=early_assert,
        )
        case_true = self._optional_case(
            obj, "case_true", path, early_assume=early_assume, early_assert=early_assert
        )
        return SplitTactic(
            split_expression=expression,
            case_false=case_false,
            case_true=case_true,
            json_path=path,
        )

    def _optional_case(
        self,
        obj: dict[str, Any],
        key: str,
        path: str,
        *,
        early_assume: bool,
        early_assert: bool,
    ) -> Tactic | None:
        """A split case is either absent (prove directly) or a tactic object."""
        if obj.get(key) is None:
            return None
        value = obj[key]
        if isinstance(value, dict) and not value:
            self._err(
                f"{path}.{key}",
                "an empty object is not a tactic: omit the field to prove "
                "this case directly",
            )
        return self.tactic(
            value, f"{path}.{key}", early_assume=early_assume, early_assert=early_assert
        )

    def _assume_guarantee(
        self,
        obj: dict[str, Any],
        path: str,
        *,
        early_assume: bool,
        early_assert: bool,
    ) -> AssumeGuaranteeTactic:
        submodules: dict[str, Objective] | None = None
        if obj.get("submodules") is not None:
            submodules = self._submodule_list(
                obj["submodules"],
                f"{path}.submodules",
                early_assume=early_assume,
                early_assert=early_assert,
            )

        auto = self._bool(obj["auto"], f"{path}.auto") if "auto" in obj else True

        instances: tuple[str, ...] | None = None
        if obj.get("instances") is not None:
            instances = self._string_list(
                obj["instances"], f"{path}.instances", allow_empty=False
            )
            self._check_distinct(list(instances), f"{path}.instances", "instance")
        elif not auto:
            self._err(
                path,
                "'instances' is required when 'auto' is false: it gives the "
                "order in which the instances are considered",
            )

        inline: tuple[str, ...] = ()
        if obj.get("inline") is not None:
            if not auto:
                self._err(
                    f"{path}.inline",
                    "'inline' is only allowed when 'auto' is true; in manual "
                    "mode every instance not listed in 'instances' is inlined",
                )
            inline = self._string_list(obj["inline"], f"{path}.inline")
            self._check_distinct(list(inline), f"{path}.inline", "inline instance")

        if inline and instances:
            raise ProofStrategyError(
                f"{path}: 'inline' and 'instances' are mutually exclusive"
            )
        return AssumeGuaranteeTactic(
            submodules=submodules,
            auto=auto,
            instances=instances,
            inline=inline,
            json_path=path,
        )

    def _submodule_list(
        self,
        value: Any,
        path: str,
        *,
        early_assume: bool,
        early_assert: bool,
    ) -> dict[str, Objective]:
        """The submodule list: each entry is a nested objective whose ``top``
        names the submodule.  The result is keyed by that name, which must be
        pairwise distinct (a JSON list is used, so a duplicate is reported as
        an error rather than silently overwriting)."""
        items = self._require_nonempty_list(value, path)
        submodules: dict[str, Objective] = {}
        for index, item in enumerate(items):
            entry_path = f"{path}[{index}]"
            objective = self.nested_objective(
                item,
                entry_path,
                early_assume=early_assume,
                early_assert=early_assert,
            )
            if objective.top in submodules:
                self._err(
                    f"{entry_path}.top",
                    f"duplicate submodule name {objective.top!r}",
                )
            submodules[objective.top] = objective
        return submodules

    def _require_nonempty_list(self, value: Any, path: str) -> list[Any]:
        if not isinstance(value, list):
            self._err(path, f"expected an array, got {type(value)}")
        if not value:
            self._err(path, "must not be an empty array (omit it for 'all')")
        return value

    def document(self, value: Any, source: Path | None) -> ProofStrategy:
        root = self._object(value, "<root>")
        self._check_keys(root, "<root>", _TOP_REQUIRED, _TOP_OPTIONAL)

        ps = self._object(root["proof_strategy"], "proof_strategy")
        self._check_keys(
            ps, "proof_strategy", _PROOF_STRATEGY_REQUIRED, _PROOF_STRATEGY_OPTIONAL
        )
        header = self._string_list(ps["header"], "proof_strategy.header")
        files = self._string_list(ps["files"], "proof_strategy.files")
        if not isinstance(ps["objectives"], list):
            self._err(
                "proof_strategy.objectives",
                f"expected an array of objectives, got {type(ps['objectives'])}",
            )
        objectives = tuple(
            self.top_level_objective(item, f"proof_strategy.objectives[{index}]")
            for index, item in enumerate(ps["objectives"])
        )
        return ProofStrategy(
            header=header,
            files=files,
            objectives=objectives,
            source=source,
            json_path="proof_strategy",
        )


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #


def parse_dict(data: Any, *, source: Path | None = None) -> ProofStrategy:
    """Parse an already-decoded JSON document into a ``ProofStrategy``.

    ``source`` is recorded on the result and used only for messages.
    """
    strategy = _Parser().document(data, source)
    logger.debug(
        "parsed proof strategy%s: %d objective(s)",
        f" from {source}" if source else "",
        len(strategy.objectives),
    )
    return strategy


def parse_string(text: str, *, source: Path | None = None) -> ProofStrategy:
    """Parse proof strategy JSON held in a string."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        where = f"{source}: " if source else ""
        raise ProofStrategyError(
            f"{where}invalid JSON at line {exc.lineno} column {exc.colno}: {exc.msg}"
        ) from exc
    return parse_dict(data, source=source)


def parse_file(path: str | Path) -> ProofStrategy:
    """Read and parse the proof strategy JSON file at ``path``."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProofStrategyError(f"cannot read proof strategy {path}: {exc}") from exc
    return parse_string(text, source=path)


# --------------------------------------------------------------------------- #
# Summary rendering (for logs and the CLI)
# --------------------------------------------------------------------------- #


def _describe_objective_label(objective: Objective) -> str:
    """A submodule/objective label: 'name' (top) when named, else just top."""
    return (
        f"{objective.name!r} (top={objective.top})" if objective.name else objective.top
    )


def _describe_tactic(tactic: Tactic, lines: list[str], indent: int) -> None:
    """Append an indented rendering of ``tactic`` (and its sub-tactics)."""
    pad = "  " * indent
    if isinstance(tactic, AssumeGuaranteeTactic):
        lines.append(f"{pad}tactic: assume_guarantee")
        if tactic.submodules is None:
            lines.append(f"{pad}  submodules: <all>")
        else:
            lines.append(f"{pad}  submodules:")
            for sub in tactic.submodules.values():
                lines.append(f"{pad}    - {_describe_objective_label(sub)}")
                if sub.tactic is not None:
                    _describe_tactic(sub.tactic, lines, indent + 3)
        if tactic.auto:
            lines.append(f"{pad}  auto: true")
            if tactic.instances is not None:
                lines.append(f"{pad}  instances: {list(tactic.instances)}")
            if tactic.inline:
                lines.append(f"{pad}  inline: {list(tactic.inline)}")
        else:
            lines.append(f"{pad}  auto: false (manual order)")
            lines.append(f"{pad}  instances: {list(tactic.instances or ())}")
    elif isinstance(tactic, SplitTactic):
        lines.append(f"{pad}tactic: split on {tactic.split_expression}")
        for label, case in (
            ("case_false", tactic.case_false),
            ("case_true", tactic.case_true),
        ):
            if case is None:
                lines.append(f"{pad}  {label}: prove directly")
            else:
                lines.append(f"{pad}  {label}:")
                _describe_tactic(case, lines, indent + 2)


def summarize(strategy: ProofStrategy) -> str:
    """A short human readable rendering of ``strategy``, for logs and the CLI."""
    lines: list[str] = []
    lines.append(f"header ({len(strategy.header)} command(s)):")
    lines.extend(f"  {command}" for command in strategy.header)
    lines.append(f"objectives ({len(strategy.objectives)}):")
    for objective in strategy.objectives:
        flags: list[str] = []
        if objective.early_assume:
            flags.append("early-assume")
        if objective.early_assert:
            flags.append("early-assert")
        suffix = f" [{', '.join(flags)}]" if flags else ""
        label = f"{objective.name!r} " if objective.name else ""
        lines.append(f"  - {label}top={objective.top}{suffix}")
        if objective.tactic is not None:
            _describe_tactic(objective.tactic, lines, 2)
        else:
            lines.append("    tactic: none (prove directly)")
    return "\n".join(lines)
