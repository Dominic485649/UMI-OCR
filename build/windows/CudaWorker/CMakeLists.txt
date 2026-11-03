cmake_minimum_required(VERSION 3.20)

if(NOT DEFINED UMIOCR_VERSION)
    message(FATAL_ERROR "UMIOCR_VERSION is required")
endif()
project(UmiOCR-CudaWorker VERSION "${UMIOCR_VERSION}" LANGUAGES CXX RC)

configure_file(resource.rc.in "${CMAKE_CURRENT_BINARY_DIR}/resource.rc" @ONLY)
add_executable(UmiOCR-CudaWorker worker_main.cpp "${CMAKE_CURRENT_BINARY_DIR}/resource.rc")
set_target_properties(UmiOCR-CudaWorker PROPERTIES
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED ON
    CXX_EXTENSIONS OFF
    MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>"
)
target_compile_definitions(UmiOCR-CudaWorker PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX UNICODE _UNICODE)
if(MSVC)
    target_compile_options(UmiOCR-CudaWorker PRIVATE /utf-8 /W4 /permissive-)
    target_link_options(UmiOCR-CudaWorker PRIVATE /INCREMENTAL:NO /MANIFEST:EMBED
        "/MANIFESTINPUT:${CMAKE_CURRENT_SOURCE_DIR}/worker.manifest")
else()
    message(FATAL_ERROR "The CUDA worker launcher requires the supported MSVC toolchain")
endif()
set_property(TARGET UmiOCR-CudaWorker APPEND PROPERTY LINK_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/worker.manifest")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/worker.manifest")
