"""Connect the existing search algorithms to the shell's signal controller."""
from shell.optimizer_controller import OptimizerController
from shell.blocks.optimizer import OptimizerBlock
from xcos_mini.optimization import optimize


def create_optimizer(params):
    return OptimizerController(params, optimize=optimize, defaults=OptimizerBlock.default_params)
