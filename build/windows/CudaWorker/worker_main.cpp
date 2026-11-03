#include <windows.h>

#include <cstdio>
#include <exception>
#include <filesystem>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using PyMain = int(__cdecl *)(int, wchar_t **);

int fail(const char *message, DWORD code = 0) noexcept
{
    std::fprintf(stderr, "%s (Windows/Python code %lu)\n", message, code);
    std::fprintf(stdout, "{\"ok\":false,\"error\":\"%s (code %lu)\"}\n", message, code);
    std::fflush(stderr);
    std::fflush(stdout);
    return 1;
}

std::filesystem::path executable_path()
{
    std::vector<wchar_t> buffer(512);
    for (;;) {
        const DWORD length = GetModuleFileNameW(nullptr, buffer.data(), static_cast<DWORD>(buffer.size()));
        if (length == 0) {
            throw std::runtime_error("GetModuleFileNameW failed");
        }
        if (length < buffer.size()) {
            return std::filesystem::path(std::wstring(buffer.data(), length));
        }
        if (buffer.size() == 32768) {
            throw std::runtime_error("Executable path exceeds the supported Windows path limit");
        }
        buffer.resize(buffer.size() * 2);
    }
}
}

int wmain(int argc, wchar_t **)
{
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX);
    if (argc != 1) {
        return fail("CUDA worker launcher does not accept command-line arguments");
    }
    if (GetACP() != CP_UTF8) {
        return fail("CUDA worker requires an effective UTF-8 process code page (Windows 10 1903 or later)", GetACP());
    }
    try {
        const auto executable = executable_path();
        const auto plugin = executable.parent_path();
        const auto runtime = plugin.parent_path().parent_path() / L"runtime";
        const auto library = runtime / L"python3.dll";
        const auto script = plugin / L"worker.py";
        if (!std::filesystem::is_regular_file(script)) {
            return fail("CUDA worker.py is missing; install the complete matching plugin");
        }
        if (!std::filesystem::is_regular_file(library)) {
            return fail("Host runtime/python3.dll is missing; install the complete base application");
        }
        const HMODULE python = LoadLibraryExW(library.c_str(), nullptr,
            LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
        if (python == nullptr) {
            return fail("Cannot load the host Python runtime", GetLastError());
        }
        // Python 与扩展模块共享进程寿命，DLL 留到进程退出时回收。
        const auto py_main = reinterpret_cast<PyMain>(GetProcAddress(python, "Py_Main"));
        if (py_main == nullptr) {
            return fail("Host Python runtime does not export Py_Main", GetLastError());
        }
        std::vector<std::wstring> arguments{
            executable.native(), L"-I", L"-B", L"-S", L"-X", L"utf8", L"-u", script.native()
        };
        std::vector<wchar_t *> pointers;
        pointers.reserve(arguments.size());
        for (auto &argument : arguments) {
            pointers.push_back(argument.data());
        }
        const int result = py_main(static_cast<int>(pointers.size()), pointers.data());
        if (result != 0) {
            fail("CUDA worker Python startup or execution failed; inspect the worker diagnostic log",
                static_cast<DWORD>(result));
        }
        return result;
    } catch (const std::exception &error) {
        std::fprintf(stderr, "%s\n", error.what());
        return fail("CUDA worker native startup failed");
    } catch (...) {
        return fail("CUDA worker native startup failed with an unknown exception");
    }
}
