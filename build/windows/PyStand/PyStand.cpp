//=====================================================================
//
// PyStand.cpp -
//
// Created by skywind on 2022/02/03
// Last Modified by hiroi-sora: 2023
//
// Source is UTF-8; Windows-facing strings use UTF-16 wchar_t literals.
//
//=====================================================================
#ifdef _MSC_VER
#define _CRT_SECURE_NO_WARNINGS 1
#endif

#include <shlwapi.h>
#include <string>
#include <string.h>
#include <winbase.h>
#include <wincon.h>

#include "PyStand.h"

//---------------------------------------------------------------------
// 启动脚本路径，解释器路径
//---------------------------------------------------------------------
#ifndef PYSTAND_STATIC_PATH
#define PYSTAND_STATIC_PATH L"\\UmiOCR-data\\main.py"
#endif
#ifndef PYSTAND_RUNTIME_PATH
#define PYSTAND_RUNTIME_PATH "\\UmiOCR-data\\runtime"
#endif

#ifdef _MSC_VER
#pragma comment(lib, "shlwapi.lib")
#endif

//---------------------------------------------------------------------
// dtor
//---------------------------------------------------------------------
PyStand::~PyStand()
{
    FreeLibrary(_hDLL);
}

//---------------------------------------------------------------------
// ctor
//---------------------------------------------------------------------
PyStand::PyStand(const wchar_t *runtime)
{
    _hDLL = NULL;
    _Py_Main = NULL;
    if (CheckEnviron(runtime) == false)
    {
        exit(1);
    }
    if (LoadPython() == false)
    {
        exit(2);
    }
}

//---------------------------------------------------------------------
// ctor for ansi
//---------------------------------------------------------------------
PyStand::PyStand(const char *runtime)
{
    _hDLL = NULL;
    _Py_Main = NULL;
    std::wstring rtp = Ansi2Unicode(runtime);
    if (CheckEnviron(rtp.c_str()) == false)
    {
        exit(1);
    }
    if (LoadPython() == false)
    {
        exit(2);
    }
}

//---------------------------------------------------------------------
// char to wchar_t
//---------------------------------------------------------------------
std::wstring PyStand::Ansi2Unicode(const char *text)
{
    int len = (int)strlen(text);
    std::wstring wide;
    int require = MultiByteToWideChar(CP_ACP, 0, text, len, NULL, 0);
    if (require > 0)
    {
        wide.resize(require);
        MultiByteToWideChar(CP_ACP, 0, text, len, &wide[0], require);
    }
    return wide;
}

//---------------------------------------------------------------------
// init: _args, _argv, _cwd, _pystand, _home, _runtime,
//---------------------------------------------------------------------
bool PyStand::CheckEnviron(const wchar_t *rtp)
{
    // init: _args, _argv
    LPWSTR *argvw;
    int argc;
    _args = GetCommandLineW();
    argvw = CommandLineToArgvW(_args.c_str(), &argc);
    if (argvw == NULL)
    {
        MessageBoxA(NULL, "Error in CommandLineToArgvW()", "ERROR", MB_OK);
        return false;
    }
    _argv.resize(argc);
    for (int i = 0; i < argc; i++)
    {
        _argv[i] = argvw[i];
    }
    LocalFree(argvw);

    // init: _cwd (current working directory)
    wchar_t path[MAX_PATH + 10];
    GetCurrentDirectoryW(MAX_PATH + 1, path);
    _cwd = path;

    // init: _pystand (full path of PyStand.exe)
    GetModuleFileNameW(NULL, path, MAX_PATH + 1);
    _pystand = path;

    // init: _home
    int size = (int)wcslen(path);
    for (; size > 0; size--)
    {
        if (path[size - 1] == L'/')
            break;
        if (path[size - 1] == L'\\')
            break;
    }
    path[size] = 0;
    SetCurrentDirectoryW(path);
    GetCurrentDirectoryW(MAX_PATH + 1, path);
    _home = path;
    SetCurrentDirectoryW(_cwd.c_str());

    // init: _runtime (embedded python directory)
    bool abspath = false;
    if (wcslen(rtp) >= 3)
    {
        if (rtp[1] == L':')
        {
            if (rtp[2] == L'/' || rtp[2] == L'\\')
                abspath = true;
        }
    }
    if (abspath == false)
    {
        _runtime = _home + L"\\" + rtp;
    }
    else
    {
        _runtime = rtp;
    }
    GetFullPathNameW(_runtime.c_str(), MAX_PATH + 1, path, NULL);
    _runtime = path;

    // check home
    std::wstring check = _runtime;
    if (!PathFileExistsW(check.c_str()))
    {
        std::wstring msg = L"Missing embedded Python3 in:\n" + check;
        MessageBoxW(NULL, msg.c_str(), L"ERROR", MB_OK);
        return false;
    }

    // check python3.dll
    std::wstring check2 = _runtime + L"\\python3.dll";
    if (!PathFileExistsW(check2.c_str()))
    {
        std::wstring msg = L"Missing python3.dll in:\r\n" + check;
        MessageBoxW(NULL, msg.c_str(), L"ERROR", MB_OK);
        return false;
    }

    // setup environment
    SetEnvironmentVariableW(L"PYSTAND", _pystand.c_str());
    SetEnvironmentVariableW(L"PYSTAND_HOME", _home.c_str());
    SetEnvironmentVariableW(L"PYSTAND_RUNTIME", _runtime.c_str());

    // unnecessary to init PYSTAND_SCRIPT here.
#if 0
	SetEnvironmentVariableW(L"PYSTAND_SCRIPT", _script.c_str());
#endif

#if 0
	wprintf(L"%s - %s\n", _pystand.c_str(), path);
	MessageBoxW(NULL, _pystand.c_str(), _home.c_str(), MB_OK);
#endif

    return true;
}

//---------------------------------------------------------------------
// load python
//---------------------------------------------------------------------
bool PyStand::LoadPython()
{
    std::wstring runtime = _runtime;
    std::wstring previous;

    // save current directory
    wchar_t path[MAX_PATH + 10];
    GetCurrentDirectoryW(MAX_PATH + 1, path);
    previous = path;

    // python dll must be load under "runtime"
    SetCurrentDirectoryW(runtime.c_str());
    // LoadLibrary
    _hDLL = (HINSTANCE)LoadLibraryA("python3.dll");
    if (_hDLL)
    {
        _Py_Main = (t_Py_Main)GetProcAddress(_hDLL, "Py_Main");
    }

    // restore director
    SetCurrentDirectoryW(previous.c_str());

    if (_hDLL == NULL)
    {
        std::wstring msg = L"Cannot load python3.dll from:\r\n" + runtime;
        MessageBoxW(NULL, msg.c_str(), L"ERROR", MB_OK);
        return false;
    }
    else if (_Py_Main == NULL)
    {
        std::wstring msg = L"Cannot find Py_Main() in:\r\n";
        msg += runtime + L"\\python3.dll";
        msg += L"\r\n\r\nThe solution can be found in the document: [ /UmiOCR-data/help.txt ]\r\n解决方法见文件：【/UmiOCR-data/帮助.txt】";
        MessageBoxW(NULL, msg.c_str(), L"ERROR", MB_OK);
        return false;
    }
    return true;
}

//---------------------------------------------------------------------
// run string
//---------------------------------------------------------------------
int PyStand::RunString()
{
    if (_Py_Main == NULL)
    {
        return -1;
    }
    int hr = 0;
    int i;
    _py_argv.resize(0);
    // init arguments
    _py_argv.push_back(_argv[0]);
    _py_argv.push_back(L"-I");
    _py_argv.push_back(L"-s");
    _py_argv.push_back(L"-S");
    _py_argv.push_back(_script);
    for (i = 1; i < (int)_argv.size(); i++)
    {
        _py_argv.push_back(_argv[i]);
    }
    // finalize arguments
    _py_args.resize(0);
    for (i = 0; i < (int)_py_argv.size(); i++)
    {
        _py_args.push_back((wchar_t *)_py_argv[i].c_str());
    }
    hr = _Py_Main((int)_py_args.size(), &_py_args[0]);
    return hr;
}

//---------------------------------------------------------------------
// LoadScript()
//---------------------------------------------------------------------
int PyStand::DetectScript()
{
    _script = _home + PYSTAND_STATIC_PATH; // 启动脚本路径
    if (!PathFileExistsW(_script.c_str())) // 检查启动文件存在
    {
        std::wstring msg = L"无法找到启动脚本：\r\nCannot find the startup script:\r\n\r\n" + _script;
        MessageBoxW(NULL, msg.c_str(), L"ERROR", MB_OK);
        return -1;
    }
    SetEnvironmentVariableW(L"PYSTAND_SCRIPT", _script.c_str());
    return 0;
}

//---------------------------------------------------------------------
// main
//---------------------------------------------------------------------

//! flag: -static
//! src:
//! link: stdc++, shlwapi, resource.o
//! prebuild: windres resource.rc -o resource.o
//! mode: win
//! int: objs

#ifdef PYSTAND_CONSOLE
int main()
#else
int WINAPI
WinMain(HINSTANCE hInst, HINSTANCE hPrevInst, LPSTR args, int show)
#endif
{
    PyStand ps(PYSTAND_RUNTIME_PATH);
    if (ps.DetectScript() != 0) // 拼接启动脚本路径，并验证存在
    {
        return 3;
    }
#ifndef PYSTAND_CONSOLE
    if (AttachConsole(ATTACH_PARENT_PROCESS))
    {
        // 输出流不存在时，重定向到控制台
        if(_fileno(stdout) < 0)
            freopen("CONOUT$", "w", stdout);
        if (_fileno(stderr) < 0)
            freopen("CONOUT$", "w", stderr);
        int fd = _fileno(stdout);
        if (fd >= 0)
        {
            std::string fn = std::to_string(fd);
            SetEnvironmentVariableA("PYSTAND_STDOUT", fn.c_str());
        }
        fd = _fileno(stdin);
        if (fd >= 0)
        {
            std::string fn = std::to_string(fd);
            SetEnvironmentVariableA("PYSTAND_STDIN", fn.c_str());
        }
    }
#endif
    int hr = ps.RunString(); // 启动！
    return hr;
}
