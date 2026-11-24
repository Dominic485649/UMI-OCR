"""把纯导出型包初始化器转为可审计的惰性导出；不修改计算实现。"""
from __future__ import annotations

import ast


def derive_lazy_init(source: str) -> tuple[str, dict]:
    tree = ast.parse(source)
    exports = None
    imports = {}
    first_import = None
    for index, statement in enumerate(tree.body):
        if index == 0 and isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str):
            continue
        if isinstance(statement, ast.ImportFrom) and statement.level == 1:
            first_import = first_import or statement.lineno
            for name in statement.names:
                if name.name == '*':
                    raise ValueError('不转换通配导出')
                exported = name.asname or name.name
                target = ('.' + statement.module, name.name) if statement.module else ('.' + name.name, None)
                if exported in imports:
                    raise ValueError('重复导出不可安全转换：' + exported)
                imports[exported] = target
            continue
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name) and statement.targets[0].id == '__all__':
            if exports is not None:
                raise ValueError('重复__all__')
            value = ast.literal_eval(statement.value)
            if not isinstance(value, (list, tuple)) or any(not isinstance(name, str) for name in value) or len(set(value)) != len(value):
                raise ValueError('__all__不是唯一字符串列表')
            exports = list(value)
            continue
        raise ValueError('初始化器含副作用/配置/非相对导入，不自动转换：' + type(statement).__name__)
    if not first_import or exports is None or any(name not in imports for name in exports):
        raise ValueError('无法把公开导出绑定到明确子模块')
    if any(name.startswith('_umi_') for name in imports):
        raise ValueError('导出与派生辅助命名空间冲突')
    # 保留原模块文档、作者和许可头，不执行或重写被导出的计算模块。
    header = '\n'.join(source.splitlines()[:first_import - 1])
    derived = header + '\n# Umi运行派生：仅按属性请求加载原导出，不改变算法、参数或类型身份。\n'
    derived += 'from importlib import import_module as _umi_import_module\n\n'
    derived += '_umi_exports = ' + repr(imports) + '\n'
    derived += '__all__ = ' + repr(exports) + '\n\n'
    derived += '''def __getattr__(name):
    try:
        module_name, attribute = _umi_exports[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    module = _umi_import_module(module_name, __name__)
    value = module if attribute is None else getattr(module, attribute)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(_umi_exports))
'''
    ast.parse(derived)
    return derived, {'exports': exports, 'bindings': imports,
                     'boundary': '仅支持无副作用的明确相对导出；需真实消费者验证后才允许按新闭包删模块。'}
