"""Cell connection helpers for the pyosys (Yosys) object model."""

from collections.abc import Iterable, Iterator

from pyosys import libyosys as ys  # type: ignore

Connection = tuple[ys.IdString, ys.SigSpec]
ConnectionBit = tuple[ys.IdString, ys.SigBit]


def _cell_connections(
    cell: ys.Cell, get_inputs: bool = False, get_outputs: bool = False
) -> Iterator[Connection]:
    """Yield the ``(conn_name, sigspec)`` pairs of ``cell`` in one direction."""
    for conn_name, conn in cell.connections_.items():
        if cell.output(conn_name) == get_outputs or cell.input(conn_name) == get_inputs:
            yield conn_name, conn


def cell_inputs(cell: ys.Cell) -> Iterator[Connection]:
    """Yield ``(conn_name, sigspec)`` for every input connection of ``cell``."""
    yield from _cell_connections(cell, get_inputs=True)


def cell_outputs(cell: ys.Cell) -> Iterator[Connection]:
    """Yield ``(conn_name, sigspec)`` for every output connection of ``cell``."""
    yield from _cell_connections(cell, get_outputs=True)


def _connection_bits(
    connections: Iterable[Connection], sigmap: ys.SigMap | None = None
) -> Iterator[ConnectionBit]:
    """Flatten ``(conn_name, sigspec)`` pairs into ``(conn_name, bit)`` pairs.

    If ``sigmap`` is given, each connection is first mapped through it, so the
    yielded bits can be used as canonical dictionary keys.
    """
    for conn_name, conn in connections:
        if sigmap is not None:
            conn = sigmap(conn)
        for bit in conn:
            yield conn_name, bit


def cell_input_bits(
    cell: ys.Cell, sigmap: ys.SigMap | None = None
) -> Iterator[ConnectionBit]:
    """Yield ``(conn_name, bit)`` for every bit read by ``cell``."""
    yield from _connection_bits(cell_inputs(cell), sigmap)


def cell_output_bits(
    cell: ys.Cell, sigmap: ys.SigMap | None = None
) -> Iterator[ConnectionBit]:
    """Yield ``(conn_name, bit)`` for every bit driven by ``cell``."""
    yield from _connection_bits(cell_outputs(cell), sigmap)
