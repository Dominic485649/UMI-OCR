"""GN的显式cc_wrapper：规范化MSVC包含、源和输出路径，不改变代码、ABI或选项语义。"""
from __future__ import annotations
import ntpath
import os
import subprocess
import sys


def normalize(arguments, cwd):
    result = []
    pending = False
    for argument in arguments:
        if pending:
            result.append(argument if pending == 'header-token' else ntpath.normpath(ntpath.join(cwd, argument)))
            pending = False
        elif argument == '/FI':
            # /FI是通过包含搜索路径解析的头文件名，不是相对工作目录的文件路径。
            result.append(argument)
            pending = 'header-token'
        elif argument in {'/I', '-I', '/Fo', '/Fd', '/Fp', '/Fe'}:
            result.append(argument)
            pending = True
        elif argument.startswith(('/Fo', '/Fd', '/Fp', '/Fe')) and len(argument) > 3:
            result.append(argument[:3] + ntpath.normpath(ntpath.join(cwd, argument[3:])))
        elif argument.startswith(('/I', '-I')) and len(argument) > 2:
            result.append(argument[:2] + ntpath.normpath(ntpath.join(cwd, argument[2:])))
        elif not argument.startswith(('/', '-', '@')) and ntpath.splitext(argument)[1].lower() in {'.c', '.cc', '.cpp', '.cxx', '.ixx', '.m', '.mm', '.s'}:
            result.append(ntpath.normpath(ntpath.join(cwd, argument)))
        else:
            result.append(argument)
    if pending:
        raise ValueError('编译路径参数缺少路径')
    return result


def dependency_output(line):
    # 本机只安装了中文MSVC资源，VSLANG=1033也会回退中文。仅将依赖信息
    # 的已知前缀映射成Ninja的默认前缀，文件路径、空格、诊断正文均不改变。
    for encoding in ('utf-8', 'gbk'):
        prefix = '注意: 包含文件:'.encode(encoding)
        if line.startswith(prefix):
            return b'Note: including file:' + line[len(prefix):]
    return line


def main():
    if len(sys.argv) < 2 or ntpath.basename(sys.argv[1]).lower() != 'cl.exe':
        raise ValueError('此包装器仅允许GN显式调用MSVC cl.exe')
    environment = os.environ.copy()
    environment['VSLANG'] = '1033'
    # 不用shell，不展开响应文件；逐行保留输出，仅规范化showIncludes前缀。
    with subprocess.Popen([sys.argv[1], *normalize(sys.argv[2:], os.getcwd())],
                          env=environment, stdout=subprocess.PIPE) as process:
        for line in process.stdout:
            sys.stdout.buffer.write(dependency_output(line))
        sys.stdout.buffer.flush()
        raise SystemExit(process.wait())


if __name__ == '__main__':
    main()
