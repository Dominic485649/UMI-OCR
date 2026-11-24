#include "HdrCapture.h"

#include <windows.h>
#include <roapi.h>

#include <d3d11_4.h>
#include <d3dcompiler.h>
#include <dxgi1_6.h>
#include <windows.graphics.capture.interop.h>
#include <windows.graphics.directx.direct3d11.interop.h>
#include <wrl/client.h>

#include <winrt/Windows.Foundation.h>
#include <winrt/Windows.Graphics.Capture.h>
#include <winrt/Windows.Graphics.DirectX.Direct3D11.h>
#include <winrt/Windows.Graphics.DirectX.h>
#include <winrt/base.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cwctype>
#include <limits>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

using Microsoft::WRL::ComPtr;
using namespace winrt;
using namespace winrt::Windows::Graphics;
using namespace winrt::Windows::Graphics::Capture;
using namespace winrt::Windows::Graphics::DirectX;
using namespace winrt::Windows::Graphics::DirectX::Direct3D11;

namespace {

constexpr std::uint32_t kAbiVersion = 1;
constexpr DWORD kCaptureTimeoutMs = 3000;
constexpr float kDefaultSdrWhiteNits = 203.0F;
constexpr float kDefaultPeakNits = 1000.0F;

constexpr char kVertexShader[] = R"hlsl(
float4 main(uint id : SV_VertexID) : SV_POSITION
{
    float2 p = float2((id << 1) & 2, id & 2);
    return float4(p.x * 2.0 - 1.0, 1.0 - p.y * 2.0, 0.0, 1.0);
}
)hlsl";

constexpr char kPixelShader[] = R"hlsl(
Texture2D<float4> source_texture : register(t0);

cbuffer ToneMapConstants : register(b0)
{
    float sdr_white_nits;
    float source_peak_nits;
    float2 padding;
};

static const float3 kLuma = float3(0.2126, 0.7152, 0.0722);

float pq_encode(float nits)
{
    const float m1 = 2610.0 / 16384.0;
    const float m2 = 2523.0 / 32.0;
    const float c1 = 3424.0 / 4096.0;
    const float c2 = 2413.0 / 128.0;
    const float c3 = 2392.0 / 128.0;
    float p = pow(saturate(nits / 10000.0), m1);
    return pow((c1 + c2 * p) / (1.0 + c3 * p), m2);
}

float pq_decode(float code)
{
    const float m1 = 2610.0 / 16384.0;
    const float m2 = 2523.0 / 32.0;
    const float c1 = 3424.0 / 4096.0;
    const float c2 = 2413.0 / 128.0;
    const float c3 = 2392.0 / 128.0;
    float p = pow(saturate(code), 1.0 / m2);
    float numerator = max(p - c1, 0.0);
    float denominator = max(c2 - c3 * p, 1e-6);
    return 10000.0 * pow(numerator / denominator, 1.0 / m1);
}

float bt2390_luminance(float nits)
{
    if (source_peak_nits <= sdr_white_nits + 0.5)
        return min(nits, sdr_white_nits);

    float source_code = pq_encode(source_peak_nits);
    float target_normalized = pq_encode(sdr_white_nits) / source_code;
    float signal = pq_encode(min(max(nits, 0.0), source_peak_nits)) / source_code;
    float knee = saturate(1.5 * target_normalized - 0.5);

    if (signal > knee && knee < 0.9999)
    {
        float t = saturate((signal - knee) / (1.0 - knee));
        float t2 = t * t;
        float t3 = t2 * t;
        signal = (2.0 * t3 - 3.0 * t2 + 1.0) * knee
               + (t3 - 2.0 * t2 + t) * (1.0 - knee)
               + (-2.0 * t3 + 3.0 * t2) * target_normalized;
    }
    return pq_decode(signal * source_code);
}

float3 gamut_compress(float3 rgb)
{
    float y = saturate(dot(rgb, kLuma));
    float minimum_channel = min(rgb.r, min(rgb.g, rgb.b));
    if (minimum_channel < 0.0)
    {
        float factor = y / max(y - minimum_channel, 1e-6);
        rgb = y.xxx + (rgb - y.xxx) * factor;
    }
    float maximum_channel = max(rgb.r, max(rgb.g, rgb.b));
    if (maximum_channel > 1.0)
    {
        float factor = (1.0 - y) / max(maximum_channel - y, 1e-6);
        rgb = y.xxx + (rgb - y.xxx) * factor;
    }
    return saturate(rgb);
}

float srgb_oetf(float linear_value)
{
    linear_value = saturate(linear_value);
    return linear_value <= 0.0031308
        ? 12.92 * linear_value
        : 1.055 * pow(linear_value, 1.0 / 2.4) - 0.055;
}

float4 main(float4 position : SV_POSITION) : SV_TARGET
{
    int2 pixel = int2(position.xy);
    float3 scrgb_nits = source_texture.Load(int3(pixel, 0)).rgb * 80.0;
    float source_y = max(dot(scrgb_nits, kLuma), 0.0);
    if (source_y <= 1e-6)
        return float4(0.0, 0.0, 0.0, 1.0);

    float mapped_y = bt2390_luminance(source_y);
    float3 linear_srgb = scrgb_nits * (mapped_y / source_y) / sdr_white_nits;
    linear_srgb = gamut_compress(linear_srgb);
    return float4(
        srgb_oetf(linear_srgb.r),
        srgb_oetf(linear_srgb.g),
        srgb_oetf(linear_srgb.b),
        1.0);
}
)hlsl";

struct ToneMapConstants {
    float sdr_white_nits;
    float source_peak_nits;
    float padding[2];
};

struct ShaderBytecode {
    std::vector<std::uint8_t> vertex;
    std::vector<std::uint8_t> pixel;
};

struct RoApartment {
    bool uninitialize = false;

    RoApartment() {
        const HRESULT result = RoInitialize(RO_INIT_MULTITHREADED);
        if (SUCCEEDED(result)) {
            uninitialize = true;
        } else if (result != RPC_E_CHANGED_MODE) {
            check_hresult(result);
        }
    }

    ~RoApartment() {
        if (uninitialize) {
            RoUninitialize();
        }
    }
};

void ClearResult(UmiHdrCaptureResult* result) {
    if (result != nullptr) {
        *result = {};
    }
}

void SetError(
    wchar_t* buffer,
    std::uint32_t buffer_chars,
    const std::wstring& message) {
    if (buffer == nullptr || buffer_chars == 0) {
        return;
    }
    const std::size_t count = std::min<std::size_t>(message.size(), buffer_chars - 1);
    std::copy_n(message.data(), count, buffer);
    buffer[count] = L'\0';
}

std::wstring Widen(const char* message) {
    if (message == nullptr || *message == '\0') {
        return L"Unknown native HDR capture error.";
    }
    const int count = MultiByteToWideChar(CP_UTF8, 0, message, -1, nullptr, 0);
    if (count <= 1) {
        return L"Unknown native HDR capture error.";
    }
    std::wstring result(static_cast<std::size_t>(count), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, message, -1, result.data(), count);
    result.pop_back();
    return result;
}

std::wstring NormalizeDisplayName(const wchar_t* name) {
    std::wstring result = name == nullptr ? L"" : name;
    constexpr wchar_t prefix[] = L"\\\\.\\";
    if (result.starts_with(prefix)) {
        result.erase(0, 4);
    }
    std::transform(result.begin(), result.end(), result.begin(), [](wchar_t value) {
        return static_cast<wchar_t>(std::towupper(value));
    });
    return result;
}

struct MonitorSearch {
    std::wstring name;
    HMONITOR monitor = nullptr;
};

struct FrameCaptureState {
    FrameCaptureState() : event(CreateEventW(nullptr, TRUE, FALSE, nullptr)) {
        if (event == nullptr) {
            throw hresult_error(HRESULT_FROM_WIN32(GetLastError()));
        }
    }

    ~FrameCaptureState() {
        CloseHandle(event);
    }

    HANDLE event;
    std::mutex mutex;
    ComPtr<ID3D11Texture2D> texture;
    SizeInt32 content_size{};
    HRESULT result = S_OK;
};

BOOL CALLBACK FindMonitorCallback(HMONITOR monitor, HDC, LPRECT, LPARAM context) {
    auto* search = reinterpret_cast<MonitorSearch*>(context);
    MONITORINFOEXW info{};
    info.cbSize = sizeof(info);
    if (GetMonitorInfoW(monitor, &info) &&
        NormalizeDisplayName(info.szDevice) == search->name) {
        search->monitor = monitor;
        return FALSE;
    }
    return TRUE;
}

HMONITOR FindMonitor(const wchar_t* display_name) {
    MonitorSearch search{NormalizeDisplayName(display_name), nullptr};
    if (search.name.empty()) {
        return nullptr;
    }
    EnumDisplayMonitors(nullptr, nullptr, FindMonitorCallback, reinterpret_cast<LPARAM>(&search));
    return search.monitor;
}

HRESULT FindAdapterAndOutput(
    HMONITOR monitor,
    ComPtr<IDXGIAdapter1>& adapter_result,
    ComPtr<IDXGIOutput6>& output_result) {
    ComPtr<IDXGIFactory1> factory;
    HRESULT result = CreateDXGIFactory1(IID_PPV_ARGS(&factory));
    if (FAILED(result)) {
        return result;
    }
    for (UINT adapter_index = 0;; ++adapter_index) {
        ComPtr<IDXGIAdapter1> adapter;
        result = factory->EnumAdapters1(adapter_index, &adapter);
        if (result == DXGI_ERROR_NOT_FOUND) {
            break;
        }
        if (FAILED(result)) {
            return result;
        }
        for (UINT output_index = 0;; ++output_index) {
            ComPtr<IDXGIOutput> output;
            result = adapter->EnumOutputs(output_index, &output);
            if (result == DXGI_ERROR_NOT_FOUND) {
                break;
            }
            if (FAILED(result)) {
                return result;
            }
            DXGI_OUTPUT_DESC description{};
            if (SUCCEEDED(output->GetDesc(&description)) && description.Monitor == monitor) {
                ComPtr<IDXGIOutput6> output6;
                result = output.As(&output6);
                if (FAILED(result)) {
                    return result;
                }
                adapter_result = adapter;
                output_result = output6;
                return S_OK;
            }
        }
    }
    return DXGI_ERROR_NOT_FOUND;
}

bool IsHdrColorSpace(const DXGI_OUTPUT_DESC1& description) {
    return description.ColorSpace == DXGI_COLOR_SPACE_RGB_FULL_G2084_NONE_P2020 ||
           description.ColorSpace == DXGI_COLOR_SPACE_RGB_STUDIO_G2084_NONE_P2020 ||
           description.ColorSpace == DXGI_COLOR_SPACE_RGB_FULL_G10_NONE_P709;
}

float QuerySdrWhiteNits(HMONITOR monitor) {
    MONITORINFOEXW monitor_info{};
    monitor_info.cbSize = sizeof(monitor_info);
    if (!GetMonitorInfoW(monitor, &monitor_info)) {
        return kDefaultSdrWhiteNits;
    }

    UINT32 path_count = 0;
    UINT32 mode_count = 0;
    LONG status = GetDisplayConfigBufferSizes(
        QDC_ONLY_ACTIVE_PATHS, &path_count, &mode_count);
    if (status != ERROR_SUCCESS) {
        return kDefaultSdrWhiteNits;
    }
    std::vector<DISPLAYCONFIG_PATH_INFO> paths(path_count);
    std::vector<DISPLAYCONFIG_MODE_INFO> modes(mode_count);
    status = QueryDisplayConfig(
        QDC_ONLY_ACTIVE_PATHS,
        &path_count,
        paths.data(),
        &mode_count,
        modes.data(),
        nullptr);
    if (status != ERROR_SUCCESS) {
        return kDefaultSdrWhiteNits;
    }

    const std::wstring monitor_name = NormalizeDisplayName(monitor_info.szDevice);
    for (UINT32 index = 0; index < path_count; ++index) {
        const auto& path = paths[index];
        DISPLAYCONFIG_SOURCE_DEVICE_NAME source{};
        source.header.type = DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME;
        source.header.size = sizeof(source);
        source.header.adapterId = path.sourceInfo.adapterId;
        source.header.id = path.sourceInfo.id;
        if (DisplayConfigGetDeviceInfo(&source.header) != ERROR_SUCCESS ||
            NormalizeDisplayName(source.viewGdiDeviceName) != monitor_name) {
            continue;
        }

        DISPLAYCONFIG_SDR_WHITE_LEVEL white_level{};
        white_level.header.type = DISPLAYCONFIG_DEVICE_INFO_GET_SDR_WHITE_LEVEL;
        white_level.header.size = sizeof(white_level);
        white_level.header.adapterId = path.targetInfo.adapterId;
        white_level.header.id = path.targetInfo.id;
        if (DisplayConfigGetDeviceInfo(&white_level.header) == ERROR_SUCCESS &&
            white_level.SDRWhiteLevel > 0) {
            return static_cast<float>(white_level.SDRWhiteLevel) / 1000.0F * 80.0F;
        }
    }
    return kDefaultSdrWhiteNits;
}

void CreateD3DDevice(
    IDXGIAdapter1* adapter,
    ComPtr<ID3D11Device>& device,
    ComPtr<ID3D11DeviceContext>& context) {
    constexpr std::array feature_levels{
        D3D_FEATURE_LEVEL_11_1,
        D3D_FEATURE_LEVEL_11_0,
    };
    D3D_FEATURE_LEVEL selected{};
    check_hresult(D3D11CreateDevice(
        adapter,
        adapter == nullptr ? D3D_DRIVER_TYPE_HARDWARE : D3D_DRIVER_TYPE_UNKNOWN,
        nullptr,
        D3D11_CREATE_DEVICE_BGRA_SUPPORT,
        feature_levels.data(),
        static_cast<UINT>(feature_levels.size()),
        D3D11_SDK_VERSION,
        &device,
        &selected,
        &context));
}

IDirect3DDevice CreateWinRtDevice(ID3D11Device* device) {
    ComPtr<IDXGIDevice> dxgi_device;
    check_hresult(device->QueryInterface(IID_PPV_ARGS(&dxgi_device)));
    IDirect3DDevice result{nullptr};
    check_hresult(CreateDirect3D11DeviceFromDXGIDevice(
        dxgi_device.Get(),
        reinterpret_cast<IInspectable**>(put_abi(result))));
    return result;
}

GraphicsCaptureItem CreateCaptureItem(HMONITOR monitor) {
    auto interop = get_activation_factory<GraphicsCaptureItem, IGraphicsCaptureItemInterop>();
    GraphicsCaptureItem item{nullptr};
    check_hresult(interop->CreateForMonitor(
        monitor,
        guid_of<GraphicsCaptureItem>(),
        put_abi(item)));
    return item;
}

ShaderBytecode CompileShaders() {
    ShaderBytecode result;
    ComPtr<ID3DBlob> vertex;
    ComPtr<ID3DBlob> pixel;
    ComPtr<ID3DBlob> errors;
    check_hresult(D3DCompile(
        kVertexShader,
        sizeof(kVertexShader) - 1,
        "UmiOCR-HdrCapture-VS",
        nullptr,
        nullptr,
        "main",
        "vs_5_0",
        D3DCOMPILE_OPTIMIZATION_LEVEL3,
        0,
        &vertex,
        &errors));
    errors.Reset();
    check_hresult(D3DCompile(
        kPixelShader,
        sizeof(kPixelShader) - 1,
        "UmiOCR-HdrCapture-PS",
        nullptr,
        nullptr,
        "main",
        "ps_5_0",
        D3DCOMPILE_OPTIMIZATION_LEVEL3,
        0,
        &pixel,
        &errors));
    const auto* vertex_bytes = static_cast<const std::uint8_t*>(vertex->GetBufferPointer());
    const auto* pixel_bytes = static_cast<const std::uint8_t*>(pixel->GetBufferPointer());
    result.vertex.assign(vertex_bytes, vertex_bytes + vertex->GetBufferSize());
    result.pixel.assign(pixel_bytes, pixel_bytes + pixel->GetBufferSize());
    return result;
}

const ShaderBytecode& GetShaders() {
    static const ShaderBytecode shaders = CompileShaders();
    return shaders;
}

void ToneMapTexture(
    ID3D11Device* device,
    ID3D11DeviceContext* context,
    ID3D11Texture2D* source,
    std::uint32_t width,
    std::uint32_t height,
    float sdr_white_nits,
    float peak_nits,
    UmiHdrCaptureResult* result) {
    D3D11_TEXTURE2D_DESC source_description{};
    source->GetDesc(&source_description);
    if (source_description.Width < width || source_description.Height < height ||
        source_description.Format != DXGI_FORMAT_R16G16B16A16_FLOAT) {
        throw hresult_error(E_INVALIDARG, L"WGC did not return an R16G16B16A16_FLOAT texture.");
    }

    D3D11_TEXTURE2D_DESC input_description{};
    input_description.Width = width;
    input_description.Height = height;
    input_description.MipLevels = 1;
    input_description.ArraySize = 1;
    input_description.Format = DXGI_FORMAT_R16G16B16A16_FLOAT;
    input_description.SampleDesc.Count = 1;
    input_description.Usage = D3D11_USAGE_DEFAULT;
    input_description.BindFlags = D3D11_BIND_SHADER_RESOURCE;
    ComPtr<ID3D11Texture2D> input_texture;
    check_hresult(device->CreateTexture2D(&input_description, nullptr, &input_texture));
    D3D11_BOX source_box{0, 0, 0, width, height, 1};
    context->CopySubresourceRegion(input_texture.Get(), 0, 0, 0, 0, source, 0, &source_box);

    ComPtr<ID3D11ShaderResourceView> source_view;
    check_hresult(device->CreateShaderResourceView(input_texture.Get(), nullptr, &source_view));

    D3D11_TEXTURE2D_DESC output_description{};
    output_description.Width = width;
    output_description.Height = height;
    output_description.MipLevels = 1;
    output_description.ArraySize = 1;
    output_description.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    output_description.SampleDesc.Count = 1;
    output_description.Usage = D3D11_USAGE_DEFAULT;
    output_description.BindFlags = D3D11_BIND_RENDER_TARGET;
    ComPtr<ID3D11Texture2D> output_texture;
    check_hresult(device->CreateTexture2D(&output_description, nullptr, &output_texture));
    ComPtr<ID3D11RenderTargetView> render_target;
    check_hresult(device->CreateRenderTargetView(output_texture.Get(), nullptr, &render_target));

    const auto& bytecode = GetShaders();
    ComPtr<ID3D11VertexShader> vertex_shader;
    ComPtr<ID3D11PixelShader> pixel_shader;
    check_hresult(device->CreateVertexShader(
        bytecode.vertex.data(), bytecode.vertex.size(), nullptr, &vertex_shader));
    check_hresult(device->CreatePixelShader(
        bytecode.pixel.data(), bytecode.pixel.size(), nullptr, &pixel_shader));

    D3D11_BUFFER_DESC constants_description{};
    constants_description.ByteWidth = sizeof(ToneMapConstants);
    constants_description.Usage = D3D11_USAGE_IMMUTABLE;
    constants_description.BindFlags = D3D11_BIND_CONSTANT_BUFFER;
    const ToneMapConstants constants{sdr_white_nits, peak_nits, {0.0F, 0.0F}};
    D3D11_SUBRESOURCE_DATA constants_data{&constants, 0, 0};
    ComPtr<ID3D11Buffer> constants_buffer;
    check_hresult(device->CreateBuffer(
        &constants_description, &constants_data, &constants_buffer));

    const D3D11_VIEWPORT viewport{
        0.0F,
        0.0F,
        static_cast<float>(width),
        static_cast<float>(height),
        0.0F,
        1.0F,
    };
    ID3D11RenderTargetView* render_targets[] = {render_target.Get()};
    ID3D11ShaderResourceView* source_views[] = {source_view.Get()};
    ID3D11Buffer* constant_buffers[] = {constants_buffer.Get()};
    context->OMSetRenderTargets(1, render_targets, nullptr);
    context->RSSetViewports(1, &viewport);
    context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    context->VSSetShader(vertex_shader.Get(), nullptr, 0);
    context->PSSetShader(pixel_shader.Get(), nullptr, 0);
    context->PSSetShaderResources(0, 1, source_views);
    context->PSSetConstantBuffers(0, 1, constant_buffers);
    context->Draw(3, 0);
    ID3D11ShaderResourceView* null_views[] = {nullptr};
    context->PSSetShaderResources(0, 1, null_views);

    D3D11_TEXTURE2D_DESC staging_description = output_description;
    staging_description.Usage = D3D11_USAGE_STAGING;
    staging_description.BindFlags = 0;
    staging_description.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    ComPtr<ID3D11Texture2D> staging;
    check_hresult(device->CreateTexture2D(&staging_description, nullptr, &staging));
    context->CopyResource(staging.Get(), output_texture.Get());

    D3D11_MAPPED_SUBRESOURCE mapped{};
    check_hresult(context->Map(staging.Get(), 0, D3D11_MAP_READ, 0, &mapped));
    const std::size_t stride = static_cast<std::size_t>(width) * 4;
    const std::size_t byte_count = stride * height;
    void* pixels = CoTaskMemAlloc(byte_count);
    if (pixels == nullptr) {
        context->Unmap(staging.Get(), 0);
        throw hresult_error(E_OUTOFMEMORY);
    }
    auto* destination = static_cast<std::uint8_t*>(pixels);
    const auto* source_bytes = static_cast<const std::uint8_t*>(mapped.pData);
    for (std::uint32_t row = 0; row < height; ++row) {
        std::copy_n(
            source_bytes + static_cast<std::size_t>(row) * mapped.RowPitch,
            stride,
            destination + static_cast<std::size_t>(row) * stride);
    }
    context->Unmap(staging.Get(), 0);

    result->pixels = pixels;
    result->width = width;
    result->height = height;
    result->stride = static_cast<std::uint32_t>(stride);
    result->used_hdr = 1;
    result->sdr_white_nits = sdr_white_nits;
    result->peak_nits = peak_nits;
}

std::int32_t CaptureMonitor(
    const wchar_t* display_name,
    float sdr_white_override_nits,
    float peak_override_nits,
    UmiHdrCaptureResult* result) {
    if (display_name == nullptr || *display_name == L'\0' || result == nullptr ||
        sdr_white_override_nits < 0.0F || peak_override_nits < 0.0F) {
        return UMI_HDR_INVALID_ARGUMENT;
    }
    if (!GraphicsCaptureSession::IsSupported()) {
        return UMI_HDR_UNSUPPORTED;
    }
    const HMONITOR monitor = FindMonitor(display_name);
    if (monitor == nullptr) {
        throw hresult_error(E_INVALIDARG, L"The Qt screen name did not match a Windows monitor.");
    }

    ComPtr<IDXGIAdapter1> adapter;
    ComPtr<IDXGIOutput6> output;
    check_hresult(FindAdapterAndOutput(monitor, adapter, output));
    DXGI_OUTPUT_DESC1 output_description{};
    check_hresult(output->GetDesc1(&output_description));
    if (!IsHdrColorSpace(output_description)) {
        return UMI_HDR_NOT_HDR;
    }

    const float system_white = QuerySdrWhiteNits(monitor);
    const float sdr_white = std::clamp(
        sdr_white_override_nits > 0.0F ? sdr_white_override_nits : system_white,
        40.0F,
        1000.0F);
    float detected_peak = output_description.MaxLuminance;
    if (!std::isfinite(detected_peak) || detected_peak <= sdr_white) {
        detected_peak = std::max(kDefaultPeakNits, sdr_white * 4.0F);
    }
    const float peak = std::clamp(
        peak_override_nits > 0.0F ? peak_override_nits : detected_peak,
        sdr_white,
        10000.0F);

    ComPtr<ID3D11Device> device;
    ComPtr<ID3D11DeviceContext> context;
    CreateD3DDevice(adapter.Get(), device, context);
    const auto winrt_device = CreateWinRtDevice(device.Get());
    const auto item = CreateCaptureItem(monitor);
    const auto item_size = item.Size();
    if (item_size.Width <= 0 || item_size.Height <= 0) {
        throw hresult_error(E_FAIL, L"Windows Graphics Capture returned an empty monitor size.");
    }
    auto frame_pool = Direct3D11CaptureFramePool::CreateFreeThreaded(
        winrt_device,
        DirectXPixelFormat::R16G16B16A16Float,
        2,
        item_size);
    auto session = frame_pool.CreateCaptureSession(item);
    try {
        session.IsCursorCaptureEnabled(false);
    } catch (...) {
    }
    try {
        session.IsBorderRequired(false);
    } catch (...) {
    }

    const auto state = std::make_shared<FrameCaptureState>();
    const auto token = frame_pool.FrameArrived(
        [state](
            Direct3D11CaptureFramePool const& sender,
            winrt::Windows::Foundation::IInspectable const&) noexcept {
            std::lock_guard lock(state->mutex);
            if (state->texture || FAILED(state->result)) {
                return;
            }
            try {
                const auto frame = sender.TryGetNextFrame();
                if (!frame) {
                    return;
                }
                const auto surface_access = frame.Surface().as<
                    ::Windows::Graphics::DirectX::Direct3D11::IDirect3DDxgiInterfaceAccess>();
                state->result = surface_access->GetInterface(
                    IID_PPV_ARGS(&state->texture));
                if (SUCCEEDED(state->result)) {
                    state->content_size = frame.ContentSize();
                }
            } catch (const hresult_error& error) {
                state->result = error.code();
            } catch (...) {
                state->result = E_FAIL;
            }
            SetEvent(state->event);
        });

    session.StartCapture();
    const DWORD wait_result = WaitForSingleObject(state->event, kCaptureTimeoutMs);
    frame_pool.FrameArrived(token);
    session.Close();
    frame_pool.Close();
    if (wait_result == WAIT_TIMEOUT) {
        return UMI_HDR_TIMEOUT;
    }
    if (wait_result != WAIT_OBJECT_0) {
        throw hresult_error(HRESULT_FROM_WIN32(GetLastError()));
    }
    std::lock_guard lock(state->mutex);
    check_hresult(state->result);
    if (!state->texture || state->content_size.Width <= 0 || state->content_size.Height <= 0) {
        throw hresult_error(E_FAIL, L"Windows Graphics Capture did not return a frame.");
    }

    ToneMapTexture(
        device.Get(),
        context.Get(),
        state->texture.Get(),
        static_cast<std::uint32_t>(state->content_size.Width),
        static_cast<std::uint32_t>(state->content_size.Height),
        sdr_white,
        peak,
        result);
    return UMI_HDR_OK;
}

std::int32_t ToneMapPixels(
    const std::uint16_t* rgba16_pixels,
    std::uint32_t width,
    std::uint32_t height,
    float sdr_white_nits,
    float peak_nits,
    UmiHdrCaptureResult* result) {
    if (rgba16_pixels == nullptr || result == nullptr || width == 0 || height == 0 ||
        width > 16384 || height > 16384 ||
        !std::isfinite(sdr_white_nits) || !std::isfinite(peak_nits) ||
        sdr_white_nits <= 0.0F || peak_nits < sdr_white_nits) {
        return UMI_HDR_INVALID_ARGUMENT;
    }
    const std::size_t row_bytes = static_cast<std::size_t>(width) * 8;
    if (row_bytes > std::numeric_limits<UINT>::max()) {
        return UMI_HDR_INVALID_ARGUMENT;
    }

    ComPtr<ID3D11Device> device;
    ComPtr<ID3D11DeviceContext> context;
    CreateD3DDevice(nullptr, device, context);
    D3D11_TEXTURE2D_DESC description{};
    description.Width = width;
    description.Height = height;
    description.MipLevels = 1;
    description.ArraySize = 1;
    description.Format = DXGI_FORMAT_R16G16B16A16_FLOAT;
    description.SampleDesc.Count = 1;
    description.Usage = D3D11_USAGE_DEFAULT;
    description.BindFlags = D3D11_BIND_SHADER_RESOURCE;
    D3D11_SUBRESOURCE_DATA data{rgba16_pixels, static_cast<UINT>(row_bytes), 0};
    ComPtr<ID3D11Texture2D> texture;
    check_hresult(device->CreateTexture2D(&description, &data, &texture));
    ToneMapTexture(
        device.Get(),
        context.Get(),
        texture.Get(),
        width,
        height,
        sdr_white_nits,
        peak_nits,
        result);
    return UMI_HDR_OK;
}

template <typename Function>
std::int32_t GuardNativeCall(
    UmiHdrCaptureResult* result,
    wchar_t* error_buffer,
    std::uint32_t error_buffer_chars,
    Function&& function) {
    ClearResult(result);
    SetError(error_buffer, error_buffer_chars, L"");
    try {
        RoApartment apartment;
        const std::int32_t status = function();
        if (status == UMI_HDR_UNSUPPORTED) {
            SetError(error_buffer, error_buffer_chars, L"Windows Graphics Capture is unavailable on this Windows version.");
        } else if (status == UMI_HDR_TIMEOUT) {
            SetError(error_buffer, error_buffer_chars, L"Windows Graphics Capture timed out waiting for a monitor frame.");
        } else if (status == UMI_HDR_INVALID_ARGUMENT) {
            SetError(error_buffer, error_buffer_chars, L"Invalid HDR capture argument.");
        }
        return status;
    } catch (const hresult_error& error) {
        SetError(error_buffer, error_buffer_chars, error.message().c_str());
    } catch (const std::exception& error) {
        SetError(error_buffer, error_buffer_chars, Widen(error.what()));
    } catch (...) {
        SetError(error_buffer, error_buffer_chars, L"Unknown native HDR capture error.");
    }
    if (result != nullptr && result->pixels != nullptr) {
        CoTaskMemFree(result->pixels);
        ClearResult(result);
    }
    return UMI_HDR_FAILED;
}

}  // namespace

std::uint32_t UmiHdrCaptureAbiVersion() {
    return kAbiVersion;
}

std::int32_t UmiCaptureMonitorHdr(
    const wchar_t* display_name,
    float sdr_white_override_nits,
    float peak_override_nits,
    UmiHdrCaptureResult* result,
    wchar_t* error_buffer,
    std::uint32_t error_buffer_chars) {
    return GuardNativeCall(result, error_buffer, error_buffer_chars, [&] {
        return CaptureMonitor(
            display_name,
            sdr_white_override_nits,
            peak_override_nits,
            result);
    });
}

std::int32_t UmiToneMapRgba16Float(
    const std::uint16_t* rgba16_pixels,
    std::uint32_t width,
    std::uint32_t height,
    float sdr_white_nits,
    float peak_nits,
    UmiHdrCaptureResult* result,
    wchar_t* error_buffer,
    std::uint32_t error_buffer_chars) {
    return GuardNativeCall(result, error_buffer, error_buffer_chars, [&] {
        return ToneMapPixels(
            rgba16_pixels,
            width,
            height,
            sdr_white_nits,
            peak_nits,
            result);
    });
}

void UmiFreeCapture(void* pixels) {
    CoTaskMemFree(pixels);
}
