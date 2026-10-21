"""停用旧版一次性原地刷新入口，避免越界访问及破坏已冻结的候选包。

该旧工具混合更新源码、插件与运行载荷，不能安全复用于当前构建。
保留文件仅用于让旧命令明确失败，不在导入或执行时访问任何产物路径。
"""

import sys


DISABLED_MESSAGE = """旧版候选包源码原地刷新工具已停用（REFRESH_DISABLED）。
此入口不会读取、刷新或删除任何候选包，也不会访问兄弟插件项目。

请使用 build/windows/Build-Release.ps1 或 build/windows/Build-GpuPlugin.ps1，
按照其当前参数在全新的构建目录重建候选包，使运行载荷、对应源码及审计记录一致。
不要单独替换已有候选包或正式发行包的源码、app.zip、ui.rcc 或来源记录。
"""


def main(argv=None):
    """仅显示停用说明；旧参数、目标路径与强制选项都不能启用刷新。"""
    args = list(sys.argv[1:] if argv is None else argv)
    if args in (["-h"], ["--help"]):
        print(DISABLED_MESSAGE)
        return 0
    print(DISABLED_MESSAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
