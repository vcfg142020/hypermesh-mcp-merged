param(
    [string]$ProjectDir = (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
)

$ErrorActionPreference = 'Stop'

function Test-AnsaToolDir {
    param([string]$PathValue)
    if ([string]::IsNullOrWhiteSpace($PathValue)) { return $false }
    try {
        $resolved = [IO.Path]::GetFullPath($PathValue)
    } catch {
        return $false
    }
    return (
        (Test-Path -LiteralPath (Join-Path $resolved 'runner.py') -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $resolved 'main.xaml') -PathType Leaf)
    )
}

function Resolve-AnsaToolDir {
    param([string]$RootDir)

    $candidates = New-Object System.Collections.Generic.List[string]
    if ($env:ANSA_AUTO_MESH_DIR) { $candidates.Add($env:ANSA_AUTO_MESH_DIR) }
    $configFile = Join-Path $RootDir 'ansa_auto_mesh_dir.txt'
    if (Test-Path -LiteralPath $configFile -PathType Leaf) {
        $saved = (Get-Content -LiteralPath $configFile -Raw -Encoding UTF8).Trim()
        if ($saved) { $candidates.Add($saved) }
    }
    $candidates.Add((Join-Path $RootDir 'ansa_mesh_tool'))
    $candidates.Add((Join-Path (Split-Path $RootDir -Parent) 'ansa_auto\ansa_mesh_tool'))
    $candidates.Add((Join-Path (Split-Path (Split-Path $RootDir -Parent) -Parent) 'ansa_auto\ansa_mesh_tool'))
    $candidates.Add('E:\ansa_auto\ansa_mesh_tool')

    foreach ($candidate in $candidates) {
        if (Test-AnsaToolDir $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = '请选择 ansa_mesh_tool 文件夹（里面应包含 runner.py 和 main.xaml）'
    $dialog.ShowNewFolderButton = $false
    if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
        if (Test-AnsaToolDir $dialog.SelectedPath) {
            return (Resolve-Path -LiteralPath $dialog.SelectedPath).Path
        }
        throw "选择的目录不是有效 ansa_mesh_tool：$($dialog.SelectedPath)"
    }

    throw '未找到 ansa_mesh_tool，且用户取消了手动选择。'
}

$root = (Resolve-Path -LiteralPath $ProjectDir).Path
Write-Host '配置 HM+ANSA 同时划分环境...' -ForegroundColor Cyan
Write-Host "HM 项目目录：$root"
Write-Host ''

$hmConfigScript = Join-Path $root '02_迁移到其他电脑_双击配置\configure_hmbatch_path.ps1'
if (-not (Test-Path -LiteralPath $hmConfigScript -PathType Leaf)) {
    throw "未找到 hmbatch 配置脚本：$hmConfigScript"
}

Write-Host '[1/3] 配置 HyperMesh hmbatch.exe...'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $hmConfigScript -ProjectDir $root
if ($LASTEXITCODE -ne 0) {
    throw "hmbatch 配置失败，退出码：$LASTEXITCODE"
}

Write-Host ''
Write-Host '[2/3] 定位 ANSA Auto Mesh 工具目录...'
$ansaToolDir = Resolve-AnsaToolDir -RootDir $root
$ansaToolConfig = Join-Path $root 'ansa_auto_mesh_dir.txt'
[System.IO.File]::WriteAllText($ansaToolConfig, $ansaToolDir + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
Write-Host "ANSA Auto Mesh 工具目录：$ansaToolDir" -ForegroundColor Green
Write-Host "已写入：$ansaToolConfig"

try {
    setx ANSA_AUTO_MESH_DIR "$ansaToolDir" | Out-Null
    Write-Host '已设置用户环境变量 ANSA_AUTO_MESH_DIR。'
} catch {
    Write-Host '警告：设置 ANSA_AUTO_MESH_DIR 环境变量失败；项目配置文件已写入，当前项目仍可使用。' -ForegroundColor Yellow
}

Write-Host ''
Write-Host '[3/3] 配置 ANSA 安装位置...'
$ansaConfigureScript = Join-Path $ansaToolDir '02_迁移到其他电脑_双击配置\configure_ansa.ps1'
if (Test-Path -LiteralPath $ansaConfigureScript -PathType Leaf) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ansaConfigureScript -ProjectDir $ansaToolDir
    if ($LASTEXITCODE -ne 0) {
        throw "ANSA 安装位置配置失败，退出码：$LASTEXITCODE"
    }
} else {
    Write-Host "未找到 ANSA 配置脚本，将跳过：$ansaConfigureScript" -ForegroundColor Yellow
}

Write-Host ''
Write-Host '配置完成。迁移到其它电脑后，通常只需要运行这一个 bat。' -ForegroundColor Green
Write-Host '之后在 HyperMesh 中重新 source launch_meshing_workflow_panel.tcl，即可使用 HM+ANSA 同时划分。'
