"""Executors for structured-data blocks on the outer diagram."""
from .starter import Starter
from .constant import Constant
from .assembler import Assembler
from .splitter import Splitter
from .display import Display

BLOCKS = {'starter': Starter(), 'input_value': Constant(),
          'param_assembler': Assembler(), 'param_splitter': Splitter(),
          'result_display': Display()}
