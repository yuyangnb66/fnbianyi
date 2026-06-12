# MiniLang 编译器生成的目标代码 (Python)
from compiler.runtime import ml_input as _ml_input, ml_write as _ml_write, ml_split_line as _ml_split_line, ml_getint as _ml_getint, ml_check_token_count as _ml_check_token_count
_vars = {}

def _ml_func(x, y):
    return (x + y)

def _ml_main():
    c = 0
    c = _ml_func(3, 4)
    print(c)
    return 0

_ml_main()
