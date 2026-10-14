cmake_minimum_required(VERSION 3.20)

if(NOT DEFINED UMIOCR_VERSION)
    set(UMIOCR_VERSION "0.0.0")
endif()
project(Umi-OCR VERSION "${UMIOCR_VERSION}" LANGUAGES CXX RC)

file(TO_CMAKE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/appicon.ico" PYSTAND_ICON_PATH)
configure_file(resource.rc.in "${CMAKE_CURRENT_BINARY_DIR}/resource.rc" @ONLY)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

option(PYSTAND_CONSOLE "Build PyStand as a console application." OFF)

# sources
set(sources
    PyStand.cpp
    "${CMAKE_CURRENT_BINARY_DIR}/resource.rc"
    )

if (PYSTAND_CONSOLE)
    add_executable(Umi-OCR ${sources})
    target_compile_definitions(Umi-OCR PRIVATE PYSTAND_CONSOLE)
else()
    add_executable(Umi-OCR WIN32 ${sources})
endif()

# static link
if (CMAKE_GENERATOR MATCHES "Visual Studio")
    set(CMAKE_FIND_LIBRARY_SUFFIXES ".lib")
    target_compile_options(Umi-OCR
        PUBLIC
        $<$<CONFIG:Debug>:/MTd>
        $<$<CONFIG:Release>:/MT>
        $<$<CONFIG:MinSizeRel>:/MT>
        )
    target_link_options(Umi-OCR PUBLIC /INCREMENTAL:NO)
else()
    # for mingw
    set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS_RELEASE} -s")
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS_RELEASE} -s")
    target_link_libraries(Umi-OCR
        -static
        shlwapi
        winmm
        )
endif()
