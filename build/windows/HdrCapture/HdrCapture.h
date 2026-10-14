#pragma once

#include <cstdint>

#ifdef UMI_HDR_CAPTURE_BUILD
#define UMI_HDR_API extern "C" __declspec(dllexport)
#else
#define UMI_HDR_API extern "C" __declspec(dllimport)
#endif

enum UmiHdrCaptureStatus : std::int32_t {
    UMI_HDR_OK = 0,
    UMI_HDR_NOT_HDR = 1,
    UMI_HDR_INVALID_ARGUMENT = 2,
    UMI_HDR_UNSUPPORTED = 3,
    UMI_HDR_FAILED = 4,
    UMI_HDR_TIMEOUT = 5,
};

struct UmiHdrCaptureResult {
    void* pixels;
    std::uint32_t width;
    std::uint32_t height;
    std::uint32_t stride;
    std::uint32_t used_hdr;
    float sdr_white_nits;
    float peak_nits;
};

UMI_HDR_API std::uint32_t UmiHdrCaptureAbiVersion();

UMI_HDR_API std::int32_t UmiCaptureMonitorHdr(
    const wchar_t* display_name,
    float sdr_white_override_nits,
    float peak_override_nits,
    UmiHdrCaptureResult* result,
    wchar_t* error_buffer,
    std::uint32_t error_buffer_chars);

UMI_HDR_API std::int32_t UmiToneMapRgba16Float(
    const std::uint16_t* rgba16_pixels,
    std::uint32_t width,
    std::uint32_t height,
    float sdr_white_nits,
    float peak_nits,
    UmiHdrCaptureResult* result,
    wchar_t* error_buffer,
    std::uint32_t error_buffer_chars);

UMI_HDR_API void UmiFreeCapture(void* pixels);
