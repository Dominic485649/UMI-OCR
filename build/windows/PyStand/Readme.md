# PyStand for UmiOCR

这是为 Umi-OCR 而适配的 PyStand 启动器，功能为启动 Python Embedded 解释器并运行指定PY脚本。源项目为 [skywind3000/PyStand](https://github.com/skywind3000/PyStand) 。

Umi-OCR 2.6.0 仅构建 Windows x64 启动器，运行时目录固定为相对路径
`UmiOCR-data/runtime`，入口固定为 `UmiOCR-data/main.py`。

### 生成解决方案

```cmd
# 创建 build 子目录，用于存储构建过程中生成的临时文件
mkdir build

cmake -S . -B build -A x64
```

### 编译

```
# 构建生成到 build/Release 目录下
cmake --build build --config Release
```
