# 仅供项目内真实 Windows 界面回归使用，不修改应用或系统权限设置。
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('ensure', 'select', 'close', 'dialog')][string]$Action,
    [Parameter(Mandatory)][string]$Folder,
    [string]$NamesJson = '[]',
    [int]$ApplicationPid = 0,
    [string]$FilePath = ''
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$folderPath = [IO.Path]::GetFullPath($Folder).TrimEnd('\', '/')
$allowed = [IO.Path]::GetFullPath((Join-Path $repo 'build')) + [IO.Path]::DirectorySeparatorChar
if (-not $folderPath.StartsWith($allowed, [StringComparison]::OrdinalIgnoreCase)) {
    throw '原生输入回归只允许访问项目 build 内的合成输入目录。'
}
if (-not (Test-Path -LiteralPath $folderPath -PathType Container)) {
    throw '合成输入目录不存在。'
}
$shell = New-Object -ComObject Shell.Application

function Find-Explorer {
    foreach ($window in @($shell.Windows())) {
        try {
            $path = [IO.Path]::GetFullPath([string]$window.Document.Folder.Self.Path).TrimEnd('\', '/')
            if ($path.Equals($folderPath, [StringComparison]::OrdinalIgnoreCase)) {
                return $window
            }
        } catch {
            # 其它 Shell 窗口不属于本回归，不读取或修改其内容。
        }
    }
    return $null
}

function Point-ForElement($Element) {
    try {
        $point = $Element.GetClickablePoint()
        return @{ x = [double]$point.X; y = [double]$point.Y }
    } catch {
        $rect = $Element.Current.BoundingRectangle
        if ($Element.Current.IsOffscreen -or $rect.Width -le 0 -or $rect.Height -le 0) { throw }
        return @{ x = [double]($rect.X + $rect.Width / 2); y = [double]($rect.Y + $rect.Height / 2) }
    }
}

if ($Action -eq 'dialog') {
    if ($ApplicationPid -le 0) { throw '必须提供本回归启动的应用进程。' }
    $selected = [IO.Path]::GetFullPath($FilePath)
    if (-not $selected.StartsWith($folderPath + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw '文件选择器只允许选中本回归的合成文件。'
    }
    $processCondition = [System.Windows.Automation.PropertyCondition]::new(
        [System.Windows.Automation.AutomationElement]::ProcessIdProperty, $ApplicationPid)
    $deadline = [DateTime]::UtcNow.AddSeconds(25)
    do {
        $windows = [System.Windows.Automation.AutomationElement]::RootElement.FindAll(
            [System.Windows.Automation.TreeScope]::Children, $processCondition)
        foreach ($window in $windows) {
            if ($window.Current.ClassName -ne '#32770') { continue }
            $edit = $null
            foreach ($automationId in @('1148', '1001')) {
                $idCondition = [System.Windows.Automation.PropertyCondition]::new(
                    [System.Windows.Automation.AutomationElement]::AutomationIdProperty, $automationId)
                $candidate = $window.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $idCondition)
                if (-not $candidate) { continue }
                if ($candidate.Current.ControlType -eq [System.Windows.Automation.ControlType]::Edit) {
                    $edit = $candidate
                } else {
                    $editCondition = [System.Windows.Automation.PropertyCondition]::new(
                        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
                        [System.Windows.Automation.ControlType]::Edit)
                    $edit = $candidate.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $editCondition)
                }
                if ($edit) { break }
            }
            if (-not $edit) { continue }
            $valuePattern = $edit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
            $valuePattern.SetValue($selected)
            $buttonCondition = [System.Windows.Automation.PropertyCondition]::new(
                [System.Windows.Automation.AutomationElement]::AutomationIdProperty, '1')
            $button = $window.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $buttonCondition)
            if (-not $button) { continue }
            $point = Point-ForElement $button
            @{ hwnd = [long]$window.Current.NativeWindowHandle; x = $point.x; y = $point.y; kind = 'native-file-dialog' } |
                ConvertTo-Json -Compress
            exit 0
        }
        # 等待 Windows 原生选择器创建；不是等待项目后台任务的轮询。
        Start-Sleep -Milliseconds 100
    } while ([DateTime]::UtcNow -lt $deadline)
    throw '未找到本回归进程的原生文件选择器或文件名输入框。'
}

$explorer = Find-Explorer
if ($Action -eq 'ensure' -and -not $explorer) {
    $shell.Explore($folderPath)
    $deadline = [DateTime]::UtcNow.AddSeconds(25)
    do {
        $explorer = Find-Explorer
        if ($explorer) { break }
        Start-Sleep -Milliseconds 100
    } while ([DateTime]::UtcNow -lt $deadline)
}
if (-not $explorer) { throw '没有找到属于合成输入目录的资源管理器窗口。' }
$hwnd = [long]$explorer.HWND
if ($Action -eq 'close') {
    # 只关闭仍停留在本回归目录的窗口，不操作用户其它资源管理器窗口。
    $explorer.Quit()
    @{ hwnd = $hwnd; closed = $true } | ConvertTo-Json -Compress
    exit 0
}
if ($Action -eq 'ensure') {
    @{ hwnd = $hwnd; folder = $folderPath } | ConvertTo-Json -Compress
    exit 0
}

$names = @($NamesJson | ConvertFrom-Json)
if ($names.Count -lt 1) { throw '至少选择一个合成文件或目录。' }
$first = $true
foreach ($name in $names) {
    if ([IO.Path]::GetFileName([string]$name) -ne $name -or [string]$name -match '[:\\/]') {
        throw '选择项必须是合成目录中的直接子项名称。'
    }
    $item = $explorer.Document.Folder.ParseName([string]$name)
    if (-not $item) { throw "资源管理器未找到合成项目：$name" }
    # SELECT、ENSUREVISIBLE、FOCUSED，第一项另带 DESELECTOTHERS。
    $flags = if ($first) { 29 } else { 25 }
    $explorer.Document.SelectItem($item, $flags)
    $first = $false
}
$root = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$hwnd)
$firstName = [string]$names[0]
$alternatives = @($firstName, [IO.Path]::GetFileNameWithoutExtension($firstName)) | Select-Object -Unique
foreach ($name in $alternatives) {
    $nameCondition = [System.Windows.Automation.PropertyCondition]::new(
        [System.Windows.Automation.AutomationElement]::NameProperty, $name)
    $elements = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $nameCondition)
    foreach ($element in $elements) {
        if ($element.Current.IsOffscreen) { continue }
        $point = Point-ForElement $element
        @{ hwnd = $hwnd; x = $point.x; y = $point.y; selected = $names; kind = 'explorer-native-selection' } |
            ConvertTo-Json -Depth 3 -Compress
        exit 0
    }
}
throw '已选择合成文件，但没有得到可用的资源管理器拖动起点。'
