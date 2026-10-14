# Windows HDR 截图测试与校准

Umi-OCR 2.6.0 在每个显示器上独立尝试 Windows Graphics Capture。HDR 屏以 `R16G16B16A16_FLOAT` 保留 scRGB 内容，在 D3D11 GPU shader 中完成 tone mapping，再转换为 IEC sRGB 8-bit 并显式标记 `QColorSpace.SRgb`。初始化或单屏捕获失败时，仅该屏回退 `QScreen.grabWindow`；截图 OCR 不会因此整体不可用。

## 映射定义

- 以 `scRGB 1.0 = 80 nits` 转换到绝对亮度。
- SDR white 默认读取 Windows `DISPLAYCONFIG_DEVICE_INFO_GET_SDR_WHITE_LEVEL`。
- HDR 峰值默认读取 DXGI 输出描述；系统数据无效时使用受限的安全默认值。
- 使用 BT.2390 高光压缩，按亮度比例保持颜色，再执行确定性色域压缩。
- 最后应用 IEC sRGB OETF，输出 BGRA 8-bit sRGB。不会把线性值当成 gamma 值，也不会直接裁剪 HDR 高光。

## 自动化测试

```powershell
$data = 'build\staging\Umi-OCR_Windows_x64_CUDA12.6\UmiOCR-data'
$python = "$data\runtime\python.exe"

& $python -I -S .\tests\test_hdr_shader.py "$data\native\UmiOCR-HdrCapture.dll"
& $python -I -S .\tests\test_capture_geometry.py
& $python -I -S .\tests\test_screenshot_capture.py $data --output .\build\test-output\screenshots
```

测试覆盖确定性 shader 输出、SDR 恒等行为、高光单调压缩、负虚拟坐标、100%-200% DPI、半开区间裁切、主屏切换、重复截图和强制 SDR 回退。

自动化捕获不验证鼠标选区窗口的实际交互、跨屏视觉观感或主窗口隐藏/恢复动画，发布前仍必须执行下面的人工步骤。

## 真实 HDR 双屏步骤

1. 准备一台开启 Windows HDR 的显示器和一台 SDR 显示器，设置不同缩放比例，例如 HDR 150%、SDR 100%，并让其中一台位于主屏左侧以产生负虚拟坐标。
2. 在 Windows HDR Calibration 或已知 HDR 测试图中同时显示暗部灰阶、SDR 白色、400/1000 nits 高光、饱和红绿蓝和细小文字。关闭会动态改变画面的第三方滤镜。
3. 保持“全局设置 → 截图 → HDR SDR 白点”和“HDR 峰值亮度”为 `0`。分别从两块屏幕截取全屏、局部和跨 DPI 边界附近的区域。
4. 检查 HDR 截图没有纯白高光硬裁剪、灰雾、双重 gamma、偏色或饱和色断层；SDR 截图应与 Windows 观感一致。
5. 检查鼠标选区四边与输出像素一致，特别关注负坐标屏幕右/下边缘；切换主屏后重复。主窗口应在截图前隐藏并恢复到原位置。
6. 连续执行“重复上一次截图”至少 10 次，确认区域、DPI 和屏幕选择不漂移。
7. 暂时重命名 `UmiOCR-data/native/UmiOCR-HdrCapture.dll` 后启动测试副本，确认日志记录 HDR fallback，HDR 屏与 SDR 屏仍能通过普通截图完成 OCR；随后恢复 DLL。
8. 记录显示器名称、Windows 版本、驱动版本、缩放、系统 SDR white、DXGI peak、捕获模式和测试图来源。不要仅凭桌面壁纸判断映射质量。

## 手动校准

只有系统读取值明显错误时才覆盖：

- “HDR SDR 白点”：填显示器上 Windows SDR 内容的目标亮度。提高数值会让映射保留更高的 SDR 白电平，但在普通显示器上查看导出图时可能显得更暗。
- “HDR 峰值亮度”：填显示器已校准的可持续峰值。提高数值会让 BT.2390 压缩更大的高光范围；错误值会降低对比度或丢失高光层次。

每次只改一个值，重新截取同一测试图并保留前后 PNG。恢复 `0` 即回到系统自动值。

Windows 10 早期版本不支持 WGC 或 monitor capture interop 时会使用 SDR 回退。该回退保证可用性，但不能保留 HDR 浮点内容，因此不能用于 HDR tone mapping 质量验收。
