"""xcos_mini: a minimal visual modeling & simulation environment.

Public API:
    core : Block, Model, Engine, Library, BlockError, AlgebraicLoopError

All block types live in the filesystem-driven block library (``blocks/``)
and are discovered at runtime by ``Library`` — there is no separate built-in
block module.
"""

from .core import (
    Block,
    Model,
    Engine,
    Library,
    BlockError,
    AlgebraicLoopError,
)

__all__ = [
    "Block",
    "Model",
    "Engine",
    "Library",
    "BlockError",
    "AlgebraicLoopError",
]

__version__ = "0.1.1"
