# MiniLang 编译器生成的目标代码 (Python)
from compiler.runtime import ml_input as _ml_input, ml_write as _ml_write, ml_split_line as _ml_split_line, ml_getint as _ml_getint
_vars = {}

def _run():
    def _entry():
        _vars['n'] = 0
        _vars['x'] = 0
        _vars['i'] = 0
        _vars['j'] = 0
        _vars['row_sum'] = 0
        _vars['total'] = 0
        _vars['t'] = 0
        _vars['line'] = ""
        _vars['t1'] = "\"请输入行数 n 和每行个数 x（空格分隔）:\""
        print(_vars['t1'])
        _vars['t2'] = "\"> \""
        _raw = _ml_input(str(_vars['t2'])).strip()
        _parts = _ml_split_line(_raw)
        try:
            _vars['n'] = int(_parts[0] if 0 < len(_parts) else '')
        except ValueError:
            try:
                _vars['n'] = int(float(_parts[0] if 0 < len(_parts) else ''))
            except ValueError:
                _vars['n'] = 0
        try:
            _vars['x'] = int(_parts[1] if 1 < len(_parts) else '')
        except ValueError:
            try:
                _vars['x'] = int(float(_parts[1] if 1 < len(_parts) else ''))
            except ValueError:
                _vars['x'] = 0
        _vars['t3'] = 0
        _vars['total'] = _vars['t3']
        _vars['t4'] = 0
        _vars['i'] = _vars['t4']
        return 'while1'

    def while1():
        _vars['t5'] = int(_vars['i'] < _vars['n'])
        if not _vars['t5']:
            return 'endwhile2'
        _vars['t6'] = "\"请输入第\""
        _vars['t7'] = 1
        _vars['t8'] = _vars['i'] + _vars['t7']
        _vars['t9'] = "\"行数据\""
        print(_vars['t6'], _vars['t8'], _vars['t9'])
        _vars['t10'] = "\"> \""
        _raw = _ml_input(str(_vars['t10'])).strip()
        _vars['line'] = str(_raw)
        _vars['t11'] = 0
        _vars['row_sum'] = _vars['t11']
        _vars['t12'] = 0
        _vars['j'] = _vars['t12']
        return 'while3'

    def while3():
        _vars['t13'] = int(_vars['j'] < _vars['x'])
        if not _vars['t13']:
            return 'endwhile4'
        _vars['t14'] = _ml_getint(str(_vars['line']), int(_vars['j']))
        _vars['t'] = _vars['t14']
        _vars['t15'] = _vars['row_sum'] + _vars['t']
        _vars['row_sum'] = _vars['t15']
        _vars['t16'] = 1
        _vars['t17'] = _vars['j'] + _vars['t16']
        _vars['j'] = _vars['t17']
        return 'while3'
        return None

    def endwhile4():
        _vars['t18'] = "\"本行之和:\""
        print(_vars['t18'])
        print(_vars['row_sum'])
        _vars['t19'] = _vars['total'] + _vars['row_sum']
        _vars['total'] = _vars['t19']
        _vars['t20'] = 1
        _vars['t21'] = _vars['i'] + _vars['t20']
        _vars['i'] = _vars['t21']
        return 'while1'
        return None

    def endwhile2():
        _vars['t22'] = "\"总和:\""
        print(_vars['t22'])
        print(_vars['total'])
        return None

    _dispatch = {
        '_entry': _entry,
        'while1': while1,
        'while3': while3,
        'endwhile4': endwhile4,
        'endwhile2': endwhile2,
    }
    pc = '_entry'
    while pc is not None:
        fn = _dispatch[pc]
        pc = fn()

_run()
