"""Studio helpers: compile dataflow for experiment tabs (FMFL/Python views use synarius_core emitters)."""

from __future__ import annotations

from dataclasses import dataclass

from synarius_core.dataflow_sim.compiler import CompiledDataflow, DataflowCompilePass
from synarius_core.dataflow_sim.context import SimulationContext


@dataclass(frozen=True)
class DataflowCompileView:
    """Result of :func:`compile_dataflow_for_view` for GUI code generation."""

    compiled: CompiledDataflow | None
    diagnostics: tuple[str, ...]


def compile_dataflow_for_view(model) -> DataflowCompileView:
    """Run the same compile pass as the simulation worker (main thread, cheap)."""
    ctx = SimulationContext(model=model)
    DataflowCompilePass().run(ctx)
    out = ctx.artifacts.get("dataflow")
    compiled = out if isinstance(out, CompiledDataflow) else None
    return DataflowCompileView(compiled=compiled, diagnostics=tuple(ctx.diagnostics))
