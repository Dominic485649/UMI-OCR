cmake_minimum_required(VERSION 3.20)

if(NOT DEFINED UMIOCR_VERSION)
    set(UMIOCR_VERSION "0.0.0")
endif()
project(UmiOCRHdrCapture VERSION "${UMIOCR_VERSION}" LANGUAGES CXX RC)

configure_file(resource.rc.in "${CMAKE_CURRENT_BINARY_DIR}/resource.rc" @ONLY)

add_library(UmiOCR-HdrCapture SHARED
    HdrCapture.cpp
    HdrCapture.h
    "${CMAKE_CURRENT_BINARY_DIR}/resource.rc"
)

target_compile_features(UmiOCR-HdrCapture PRIVATE cxx_std_20)
target_compile_definitions(UmiOCR-HdrCapture PRIVATE
    UMI_HDR_CAPTURE_BUILD
    WIN32_LEAN_AND_MEAN
    NOMINMAX
    UNICODE
    _UNICODE
    _WIN32_WINNT=0x0A00
)
target_compile_options(UmiOCR-HdrCapture PRIVATE
    /W4
    /EHsc
    /permissive-
    /utf-8
    $<$<CONFIG:Release>:/MT>
    $<$<CONFIG:MinSizeRel>:/MT>
    $<$<CONFIG:Debug>:/MTd>
)
target_link_options(UmiOCR-HdrCapture PRIVATE /INCREMENTAL:NO)
target_link_libraries(UmiOCR-HdrCapture PRIVATE
    d3d11
    dxgi
    d3dcompiler
    runtimeobject
    windowsapp
)

set_target_properties(UmiOCR-HdrCapture PROPERTIES
    OUTPUT_NAME "UmiOCR-HdrCapture"
)
