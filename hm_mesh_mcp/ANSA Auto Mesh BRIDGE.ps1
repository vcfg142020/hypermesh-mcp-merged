Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName System.Windows.Forms

$bridgeRoot = $PSScriptRoot
$configuredAnsaToolDir = ''
$configuredAnsaToolFile = Join-Path $bridgeRoot 'ansa_auto_mesh_dir.txt'
if (Test-Path -LiteralPath $configuredAnsaToolFile) {
    try { $configuredAnsaToolDir = (Get-Content -LiteralPath $configuredAnsaToolFile -Raw -Encoding UTF8).Trim() } catch { }
}
$candidateBases = @(
    $configuredAnsaToolDir,
    $env:ANSA_AUTO_MESH_DIR,
    (Join-Path $bridgeRoot 'ansa_mesh_tool'),
    (Join-Path (Split-Path $bridgeRoot -Parent) 'ansa_auto\ansa_mesh_tool'),
    (Join-Path (Split-Path (Split-Path $bridgeRoot -Parent) -Parent) 'ansa_auto\ansa_mesh_tool'),
    'E:\ansa_auto\ansa_mesh_tool'
) | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) }
$base = $null
foreach ($candidateBase in $candidateBases) {
    $resolvedCandidate = [IO.Path]::GetFullPath([string]$candidateBase)
    if ((Test-Path -LiteralPath (Join-Path $resolvedCandidate 'main.xaml')) -and
        (Test-Path -LiteralPath (Join-Path $resolvedCandidate 'runner.py'))) {
        $base = $resolvedCandidate
        break
    }
}
if (-not $base) {
    [System.Windows.MessageBox]::Show(
        "没有找到 ANSA Auto Mesh 工具目录。`n`n可选做法：`n1. 将 ansa_mesh_tool 放到本目录或 E:\ansa_auto\ansa_mesh_tool；`n2. 或设置环境变量 ANSA_AUTO_MESH_DIR 指向 ansa_mesh_tool。",
        'ANSA Bridge Failed'
    ) | Out-Null
    exit 1
}
$bridgeStatePath = Join-Path $bridgeRoot 'runs\ansa_selected_step.json'
$bridgeRunStatePath = Join-Path $bridgeRoot 'runs\ansa_parallel_job.json'
$settingsPath = Join-Path $base 'settings.json'
$mesh = Join-Path $base 'templates\robot-2mm.ansa_mpar'
$quality = Join-Path $base 'templates\subframe.ansa_qual'
$logs = [System.Collections.Generic.List[string]]::new()
$process = $null; $jobDir = ''; $logFile = ''; $logOffset = 0; $ansaLauncher = ''; $completed = $false
$externalParallelStamp = ''; $externalJobDir = ''; $externalLogFile = ''; $externalResultFile = ''; $externalStopFile = ''; $externalLogOffset = 0; $externalMonitoring = $false; $lastAnsaPercent = -1
$filletRules = @(
    [pscustomobject]@{Radius='1.-2.';Width='1.-2.';Rows=1},
    [pscustomobject]@{Radius='2.1-4.';Width='2.1-4.';Rows=2},
    [pscustomobject]@{Radius='4.1-15.';Width='4.1-15.';Rows=3},
    [pscustomobject]@{Radius='15.1-24.';Width='15.1-24.';Rows=5}
)

# Layout is kept in a standalone XAML file so the high-DPI window stays compact
# and entirely within a typical 1366×768 work area.
[xml]$xaml = Get-Content -LiteralPath (Join-Path $base 'main.xaml') -Raw -Encoding UTF8
$reader = New-Object System.Xml.XmlNodeReader $xaml
$window = [Windows.Markup.XamlReader]::Load($reader)
$c=@{}; 'StepPath','OutputPath','DropZone','DropText','ClearStep','StepBrowse','OutputBrowse','MeshName','QualityName','MeshBrowse','QualityBrowse','Target','Minimum','FilletSummary','FilletRules','Start','Stop','Status','Progress','S0','S1','S2','S3','S4','S5','Logs' | % { $c[$_]=$window.FindName($_) }

function AddLog($t){$logs.Add(("[" + (Get-Date -Format HH:mm:ss) + "] " + [string]$t))}
function SetStage($i,$d){0..5|%{$name=($c["S$_"].Text-split"`n")[0];$state=if($_-lt$i){'已完成'}elseif($_-eq$i){$d}else{'待执行'};$c["S$_"].Text="$name`n$state"};$c.Progress.Value=[Math]::Min(6,$i+1)}
function UpdateAnsaUiFromLogLine($line){
    if ([string]::IsNullOrWhiteSpace($line)) { return }
    AddLog $line
    if ($line -match '^@@STAGE\s+(\S+)\s+(.+)$') {
        $map = @{
            'prepare'=@(0,'后台 ANSA 已启动')
            'import'=@(1,'正在导入 STEP')
            'repair'=@(2,'正在检查与修复几何')
            'mesh'=@(3,'正在执行 Batch Mesh')
            'export'=@(4,'正在导出 Abaqus INP')
            'complete'=@(5,'处理完成')
        }
        if ($map.ContainsKey($matches[1])) {
            $stage=$map[$matches[1]]
            if ($matches[1] -eq 'complete') { SetStage $stage[0] '已完成'; $script:completed = $true }
            else { SetStage $stage[0] '进行中' }
            $c.Status.Text = $stage[1]
        }
    } elseif ($line -match '^\s*(\d{1,3})%\s+\[') {
        $pct = [Math]::Min(100, [Math]::Max(0, [int]$matches[1]))
        if ($pct -lt $script:lastAnsaPercent) { return }
        $script:lastAnsaPercent = $pct
        $c.Status.Text = "ANSA 后台划分中：$pct%"
        $c.Progress.Value = [Math]::Min(6, [Math]::Max(0, $pct * 0.06))
    }
}
function ReadTextShared($path){
    $stream = [IO.File]::Open($path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
    try {
        $reader = [IO.StreamReader]::new($stream, [Text.Encoding]::UTF8, $true)
        try { return $reader.ReadToEnd() }
        finally { $reader.Dispose() }
    } finally {
        if ($stream) { $stream.Dispose() }
    }
}
function CompleteExternalParallelMonitor($state){
    $script:externalMonitoring = $false
    $c.Start.IsEnabled = $true
    $c.Stop.IsEnabled = $false
    if ($state.success) {
        $script:completed = $true
        SetStage 5 '已完成'
        $msg = if ($state.message) { [string]$state.message } else { 'ANSA 并行任务完成。' }
        $c.Status.Text = $msg
        if ($state.inp_file) { AddLog ("ANSA INP：" + [string]$state.inp_file) }
    } else {
        $c.Status.Text = if ($state.message) { [string]$state.message } else { 'ANSA 并行任务结束，但未成功。' }
    }
}
function CheckExternalParallelJob{
    if ($process -and -not $process.HasExited) { return }
    if (-not (Test-Path $bridgeRunStatePath)) { return }
    try {
        $state = ReadTextShared $bridgeRunStatePath | ConvertFrom-Json
    } catch {
        AddLog ("读取 HM+ANSA 并行状态失败：" + $_.Exception.Message)
        return
    }
    if (-not $state.stamp) { return }
    if (-not $script:externalMonitoring -and ($state.active -eq $false)) { return }
    if ([string]$state.stamp -ne $script:externalParallelStamp) {
        $script:externalParallelStamp = [string]$state.stamp
        $script:externalJobDir = [string]$state.job_dir
        $script:externalLogFile = [string]$state.runner_log
        $script:externalResultFile = [string]$state.result_json
        $script:externalStopFile = [string]$state.stop_file
        $script:externalLogOffset = 0
        $script:externalMonitoring = $true
        $script:completed = $false
        $script:lastAnsaPercent = -1
        $logs.Clear()
        SetStage 0 '进行中'
        $c.Status.Text = 'HM+ANSA 同时划分：ANSA 后台已启动'
        $c.Start.IsEnabled = $false
        $c.Stop.IsEnabled = $true
        AddLog ("正在监控 HM 发起的 ANSA 并行任务：" + $script:externalJobDir)
    }
    if ($script:externalMonitoring -and $script:externalLogFile -and (Test-Path $script:externalLogFile)) {
        $text = ReadTextShared $script:externalLogFile
        if ($text.Length -gt $script:externalLogOffset) {
            $new = $text.Substring($script:externalLogOffset); $script:externalLogOffset = $text.Length
            $new -split "`r?`n" | ForEach-Object { UpdateAnsaUiFromLogLine $_ }
        }
    }
    if ($script:externalMonitoring -and ($state.active -eq $false)) {
        CompleteExternalParallelMonitor $state
    }
}
function GetRulesForBridge { @($filletRules | ForEach-Object { [ordered]@{radius=$_.Radius;width=$_.Width;rows=[int]$_.Rows} }) }
function WriteBridgeState{
    try {
        New-Item -ItemType Directory -Force -Path (Split-Path $bridgeStatePath -Parent) | Out-Null
        $step = [string]$c.StepPath.Text
        $stepName = if ($step) { [IO.Path]::GetFileName($step) } else { '' }
        [ordered]@{
            step_path=$step
            step_name=$stepName
            output_path=[string]$c.OutputPath.Text
            mpar_template=$mesh
            qual_template=$quality
            ansa_launcher=$ansaLauncher
            target_length=[string]$c.Target.Text
            minimum_length=[string]$c.Minimum.Text
            fillet_rules=(GetRulesForBridge)
            updated_at=(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
            source='ANSA Auto Mesh BRIDGE.ps1'
        } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $bridgeStatePath -Encoding UTF8
    } catch {
        AddLog ("同步 ANSA 状态给 HM 失败：" + $_.Exception.Message)
    }
}
function SetStep($f){if([IO.Path]::GetExtension($f).ToLower()-notin'.stp','.step'){[Windows.MessageBox]::Show('请选择 .stp 或 .step 文件。')|Out-Null;return};$c.StepPath.Text=$f;$c.OutputPath.Text=Join-Path([IO.Path]::GetDirectoryName($f))(([IO.Path]::GetFileNameWithoutExtension($f))+'_ANSA_Mesh');$c.DropText.Text="已选择  ·  $([IO.Path]::GetFileName($f))";$c.ClearStep.Visibility='Visible';$c.Status.Text='STEP 文件已就绪';WriteBridgeState;AddLog "已同步 ANSA STEP 给 HM 实验面板：$bridgeStatePath"}
function ClearStep{$c.StepPath.Text='';$c.DropText.Text='拖拽 STEP 文件到这里  ·  点击选择';$c.ClearStep.Visibility='Collapsed';$c.Status.Text='等待导入 STEP 文件';WriteBridgeState}
function PickStep{$d=New-Object Microsoft.Win32.OpenFileDialog;$d.Filter='STEP 文件|*.stp;*.step';if($d.ShowDialog()){SetStep $d.FileName}}
function PickFolder{$d=New-Object Windows.Forms.FolderBrowserDialog;if($d.ShowDialog()-eq'OK'){$c.OutputPath.Text=$d.SelectedPath;WriteBridgeState}}
function PickTemplate($isMesh){$d=New-Object Microsoft.Win32.OpenFileDialog;$d.Filter=if($isMesh){'ANSA Mesh Parameters|*.ansa_mpar'}else{'ANSA Quality Criteria|*.ansa_qual'};if($d.ShowDialog()){if($isMesh){$script:mesh=$d.FileName;$c.MeshName.Text=[IO.Path]::GetFileName($mesh)}else{$script:quality=$d.FileName;$c.QualityName.Text=[IO.Path]::GetFileName($quality)};WriteBridgeState}}
function UpdateFilletSummary{$c.FilletSummary.Text = (($filletRules | ForEach-Object { "$($_.Radius):R$($_.Rows)" }) -join '  ')}
function GetAvailableOutputBasename($dir,$stem){
    $candidate = $stem
    $index = 1
    while (Test-Path -LiteralPath (Join-Path $dir ($candidate + '.inp'))) {
        $candidate = ('{0}_{1:D3}' -f $stem, $index)
        $index++
    }
    return $candidate
}
function ShowFilletRules{
    [xml]$ruleXaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="圆角规则" Width="560" Height="330" ResizeMode="NoResize"
        WindowStartupLocation="CenterOwner" Background="#F4F7FB"
        FontFamily="Microsoft YaHei UI">
  <Grid Margin="16">
    <Grid.RowDefinitions><RowDefinition Height="28"/><RowDefinition Height="174"/><RowDefinition Height="54"/></Grid.RowDefinitions>
    <TextBlock Text="设置 Fillets treatment：半径范围、宽度范围与 Rows" FontSize="13" FontWeight="SemiBold" Foreground="#163E68"/>
    <Border Grid.Row="1" Background="White" BorderBrush="#D7E2ED" BorderThickness="1" CornerRadius="6" Padding="10">
      <Grid>
        <Grid.RowDefinitions><RowDefinition Height="24"/><RowDefinition Height="30"/><RowDefinition Height="30"/><RowDefinition Height="30"/><RowDefinition Height="30"/></Grid.RowDefinitions>
        <Grid.ColumnDefinitions><ColumnDefinition Width="42"/><ColumnDefinition Width="150"/><ColumnDefinition Width="150"/><ColumnDefinition Width="80"/></Grid.ColumnDefinitions>
        <TextBlock Text="#" FontWeight="SemiBold" Foreground="#617286"/>
        <TextBlock Grid.Column="1" Text="Radius" FontWeight="SemiBold" Foreground="#617286"/>
        <TextBlock Grid.Column="2" Text="Width" FontWeight="SemiBold" Foreground="#617286"/>
        <TextBlock Grid.Column="3" Text="Rows" FontWeight="SemiBold" Foreground="#617286"/>
        <TextBlock Grid.Row="1" Text="1" VerticalAlignment="Center"/><TextBox x:Name="Radius1" Grid.Row="1" Grid.Column="1" Margin="0,2,10,2"/><TextBox x:Name="Width1" Grid.Row="1" Grid.Column="2" Margin="0,2,10,2"/><TextBox x:Name="Rows1" Grid.Row="1" Grid.Column="3" Margin="0,2,0,2"/>
        <TextBlock Grid.Row="2" Text="2" VerticalAlignment="Center"/><TextBox x:Name="Radius2" Grid.Row="2" Grid.Column="1" Margin="0,2,10,2"/><TextBox x:Name="Width2" Grid.Row="2" Grid.Column="2" Margin="0,2,10,2"/><TextBox x:Name="Rows2" Grid.Row="2" Grid.Column="3" Margin="0,2,0,2"/>
        <TextBlock Grid.Row="3" Text="3" VerticalAlignment="Center"/><TextBox x:Name="Radius3" Grid.Row="3" Grid.Column="1" Margin="0,2,10,2"/><TextBox x:Name="Width3" Grid.Row="3" Grid.Column="2" Margin="0,2,10,2"/><TextBox x:Name="Rows3" Grid.Row="3" Grid.Column="3" Margin="0,2,0,2"/>
        <TextBlock Grid.Row="4" Text="4" VerticalAlignment="Center"/><TextBox x:Name="Radius4" Grid.Row="4" Grid.Column="1" Margin="0,2,10,2"/><TextBox x:Name="Width4" Grid.Row="4" Grid.Column="2" Margin="0,2,10,2"/><TextBox x:Name="Rows4" Grid.Row="4" Grid.Column="3" Margin="0,2,0,2"/>
      </Grid>
    </Border>
    <StackPanel Grid.Row="2" Orientation="Horizontal" HorizontalAlignment="Right" VerticalAlignment="Bottom">
      <Button x:Name="Cancel" Content="取消" Width="76" Height="28" Margin="0,0,8,0"/>
      <Button x:Name="Ok" Content="确定" Width="88" Height="28" Background="#1976D2" Foreground="White"/>
    </StackPanel>
  </Grid>
</Window>
'@
    $reader = New-Object System.Xml.XmlNodeReader $ruleXaml
    $dialog = [Windows.Markup.XamlReader]::Load($reader)
    $dialog.Owner = $window
    $d=@{}; 'Radius1','Width1','Rows1','Radius2','Width2','Rows2','Radius3','Width3','Rows3','Radius4','Width4','Rows4','Ok','Cancel' | % { $d[$_]=$dialog.FindName($_) }
    for($i=1;$i -le 4;$i++){ $rule=$filletRules[$i-1]; $d["Radius$i"].Text=$rule.Radius; $d["Width$i"].Text=$rule.Width; $d["Rows$i"].Text=[string]$rule.Rows }
    $d.Cancel.Add_Click({$dialog.DialogResult=$false})
    $d.Ok.Add_Click({
        try {
            $newRules = @()
            for($i=1;$i -le 4;$i++){
                $radius = $d["Radius$i"].Text.Trim(); $width = $d["Width$i"].Text.Trim(); [int]$rows = $d["Rows$i"].Text
                if ([string]::IsNullOrWhiteSpace($radius) -or [string]::IsNullOrWhiteSpace($width)) { throw 'Radius 和 Width 不能为空。' }
                if ($radius -match '\|\|' -or $width -match '\|\|') { throw 'Radius 和 Width 不能包含 ||。' }
                if ($rows -lt 1 -or $rows -gt 99) { throw 'Rows 必须是 1 到 99 的整数。' }
                $newRules += [pscustomobject]@{Radius=$radius;Width=$width;Rows=$rows}
            }
            $script:filletRules = $newRules
            UpdateFilletSummary
            WriteBridgeState
            $dialog.DialogResult=$true
        } catch { [Windows.MessageBox]::Show($_.Exception.Message,'圆角规则') | Out-Null }
    })
    [void]$dialog.ShowDialog()
}
if(Test-Path $settingsPath){try{$s=Get-Content $settingsPath -Raw|ConvertFrom-Json;if($s.MeshTemplate-and(Test-Path $s.MeshTemplate)){$mesh=$s.MeshTemplate};if($s.QualityTemplate-and(Test-Path $s.QualityTemplate)){$quality=$s.QualityTemplate};if($s.OutputFolder){$c.OutputPath.Text=$s.OutputFolder};if($s.AnsaLauncher-and(Test-Path $s.AnsaLauncher)){$ansaLauncher=$s.AnsaLauncher};if($s.FilletRules-and $s.FilletRules.Count -eq 4){$filletRules=@($s.FilletRules | ForEach-Object {[pscustomobject]@{Radius=[string]$_.Radius;Width=[string]$_.Width;Rows=[int]$_.Rows}})}}catch{}}
$c.MeshName.Text=[IO.Path]::GetFileName($mesh);$c.QualityName.Text=[IO.Path]::GetFileName($quality)
UpdateFilletSummary
$c.StepBrowse.Add_Click({PickStep});$c.OutputBrowse.Add_Click({PickFolder});$c.MeshBrowse.Add_Click({PickTemplate $true});$c.QualityBrowse.Add_Click({PickTemplate $false});$c.FilletRules.Add_Click({ShowFilletRules});$c.ClearStep.Add_Click({param($s,$e);ClearStep;$e.Handled=$true});$c.Target.Add_LostFocus({WriteBridgeState});$c.Minimum.Add_LostFocus({WriteBridgeState});$c.DropZone.Add_MouseLeftButtonDown({PickStep});$c.DropZone.Add_DragEnter({param($s,$e);$e.Effects=if($e.Data.GetDataPresent([Windows.DataFormats]::FileDrop)){[Windows.DragDropEffects]::Copy}else{[Windows.DragDropEffects]::None};$e.Handled=$true});$c.DropZone.Add_Drop({param($s,$e);$files=$e.Data.GetData([Windows.DataFormats]::FileDrop);if($files.Count){SetStep $files[0]}})
$timer = New-Object Windows.Threading.DispatcherTimer
$timer.Interval = [TimeSpan]::FromMilliseconds(500)
$timer.Add_Tick({
    try {
    CheckExternalParallelJob
    if ($logFile -and (Test-Path $logFile)) {
        $text = ReadTextShared $logFile
        if ($text.Length -gt $logOffset) {
            $new = $text.Substring($logOffset); $script:logOffset = $text.Length
            $new -split "`r?`n" | ForEach-Object { UpdateAnsaUiFromLogLine $_ }
        }
    }
    if ($process -and $process.HasExited) {
        $timer.Stop(); $c.Start.IsEnabled = $true; $c.Stop.IsEnabled = $false
        $result = Join-Path $jobDir 'result.json'
        if (Test-Path $result) {
            $r = ReadTextShared $result | ConvertFrom-Json
            if ($r.success) {
                $script:completed = $true; SetStage 5 '已完成'; $c.Status.Text = $r.message
                $detail = "$($r.message)`n`nINP：$($r.inp_file)"
                if ($r.meshing -and $r.meshing.skipped_part_count -gt 0) {
                    $detail += "`n`n以下部件因几何问题未划分："
                    $skipped = @()
                    if ($r.geometry -and $r.geometry.bad_parts) { $skipped = @($r.geometry.bad_parts) }
                    elseif ($r.meshing.skipped_parts) { $skipped = @($r.meshing.skipped_parts) }
                    $skipped | Select-Object -First 12 | ForEach-Object {
                        $label = if ($_.label) { $_.label } elseif ($_.name) { $_.name } else { $_.key }
                        $types = if ($_.error_types) { "（" + (($_.error_types) -join ', ') + "）" } else { "" }
                        $detail += "`n- $label$types"
                    }
                    if ($skipped.Count -gt 12) { $detail += "`n... 还有 $($skipped.Count - 12) 个部件，详见运行日志。" }
                }
                $detail += "`n`n后台文件：$jobDir"
                try { [Windows.MessageBox]::Show($detail,'处理完成') | Out-Null } catch { AddLog ("完成提示显示失败：" + $_.Exception.Message) }
            }
            else { $c.Status.Text = '任务失败，请查看日志'; [Windows.MessageBox]::Show($r.message,'ANSA 自动网格失败') | Out-Null }
        } else { $c.Status.Text = '后台启动失败，请查看日志'; [Windows.MessageBox]::Show('后台任务未生成 result.json。请在“查看运行日志”中检查启动信息。','ANSA 自动网格失败') | Out-Null }
    }
    } catch {
        $timer.Stop(); $c.Start.IsEnabled = $true; $c.Stop.IsEnabled = $false
        if ($completed) { SetStage 5 '已完成'; $c.Status.Text = '处理完成：已生成 INP。' }
        else { $c.Status.Text = '状态更新失败，请查看运行日志' }
        AddLog ("界面状态更新错误：" + $_.Exception.Message)
    }
})
$c.Start.Add_Click({
    try {
        if (-not (Test-Path $c.StepPath.Text)) { throw '请先选择 STEP 文件。' }
        if (-not (Test-Path $ansaLauncher)) { throw '请先双击“02_迁移到其他电脑_双击配置\配置 ANSA 安装位置.bat”完成一次配置。' }
        [decimal]$a = $c.Target.Text; [decimal]$b = $c.Minimum.Text
        if ($a -le 0 -or $b -le 0 -or $b -gt $a) { throw '网格尺寸必须大于 0，且最小尺寸不能大于目标尺寸。' }
        $publicOutDir = [IO.Path]::GetFullPath($c.OutputPath.Text)
        New-Item -ItemType Directory -Path $publicOutDir -Force | Out-Null
        $stepStem = [IO.Path]::GetFileNameWithoutExtension($c.StepPath.Text)
        $outputBasename = GetAvailableOutputBasename $publicOutDir $stepStem
        $workRoot = Join-Path $base 'work'
        New-Item -ItemType Directory -Path $workRoot -Force | Out-Null
        $script:jobDir = Join-Path $workRoot ($outputBasename + '_job_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
        New-Item -ItemType Directory -Path $jobDir -Force | Out-Null
        $rulesForJob = @($filletRules | ForEach-Object { [ordered]@{radius=$_.Radius;width=$_.Width;rows=[int]$_.Rows} })
        $outputRenameMessage = $null
        if ($outputBasename -ne $stepStem) { $outputRenameMessage = "检测到同名 INP，自动改名为：" + $outputBasename + ".inp" }
        $job = [ordered]@{source_step=[IO.Path]::GetFullPath($c.StepPath.Text);mpar_template=[IO.Path]::GetFullPath($mesh);qual_template=[IO.Path]::GetFullPath($quality);ansa_launcher=[IO.Path]::GetFullPath($ansaLauncher);output_dir=[IO.Path]::GetFullPath($jobDir);final_output_dir=$publicOutDir;output_basename=$outputBasename;target_length=$a;minimum_length=$b;fillet_rules=$rulesForJob}
        $cfg = Join-Path $jobDir 'job_config.json'; $job | ConvertTo-Json -Depth 5 | Set-Content $cfg -Encoding UTF8
        [ordered]@{MeshTemplate=$mesh;QualityTemplate=$quality;OutputFolder=$c.OutputPath.Text;AnsaLauncher=$ansaLauncher;FilletRules=$rulesForJob} | ConvertTo-Json -Depth 5 | Set-Content $settingsPath -Encoding UTF8
        $script:logFile = Join-Path $jobDir 'runner.log'; $script:logOffset = 0; $script:completed = $false; $script:lastAnsaPercent = -1; $logs.Clear(); if ($outputRenameMessage) { AddLog $outputRenameMessage }; SetStage 0 '进行中'; $c.Status.Text = '正在启动后台 ANSA…'; $c.Start.IsEnabled = $false; $c.Stop.IsEnabled = $true
        $runner = Join-Path $base 'runner.py'; $psi = New-Object Diagnostics.ProcessStartInfo
        $pyLauncher = Get-Command 'py.exe' -ErrorAction SilentlyContinue
        if ($pyLauncher) {
            $psi.FileName = $pyLauncher.Source
            $psi.Arguments = "-3 `"$runner`" `"$cfg`""
        } else {
            $python = Get-Command 'python.exe' -ErrorAction SilentlyContinue
            if (-not $python) { throw '未找到 Python。请安装 Python 3，或确认 python.exe/py.exe 已加入 PATH。' }
            $psi.FileName = $python.Source
            $psi.Arguments = "`"$runner`" `"$cfg`""
        }
        $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true
        $script:process = New-Object Diagnostics.Process; $process.StartInfo = $psi; [void]$process.Start(); $timer.Start()
    } catch { $c.Start.IsEnabled = $true; $c.Stop.IsEnabled = $false; [Windows.MessageBox]::Show($_.Exception.Message,'ANSA Auto Mesh') | Out-Null }
})
$c.Stop.Add_Click({
    if ($externalMonitoring -and $externalStopFile) {
        try {
            AddLog '用户在 ANSA 窗口请求停止 HM+ANSA 同时划分。'
            New-Item -ItemType Directory -Force -Path (Split-Path $externalStopFile -Parent) | Out-Null
            ("stop requested from ANSA window at " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')) | Set-Content -LiteralPath $externalStopFile -Encoding UTF8
            $c.Status.Text = '已请求停止 HM+ANSA 同时划分'
            $c.Stop.IsEnabled = $false
        } catch { [Windows.MessageBox]::Show("停止请求失败：$($_.Exception.Message)",'ANSA Auto Mesh') | Out-Null }
    } elseif ($process -and -not $process.HasExited) {
        try {
            AddLog '用户请求停止任务。'
            Start-Process -FilePath 'taskkill.exe' -ArgumentList @('/PID', $process.Id, '/T', '/F') -NoNewWindow -Wait
            $timer.Stop(); $c.Start.IsEnabled = $true; $c.Stop.IsEnabled = $false
            $c.Status.Text = '任务已停止'; SetStage 0 '已停止'
        } catch { [Windows.MessageBox]::Show("停止失败：$($_.Exception.Message)",'ANSA Auto Mesh') | Out-Null }
    }
})
$c.Logs.Add_Click({
    $w=New-Object Windows.Window; $w.Title='ANSA Auto Mesh · 运行日志'; $w.Width=760; $w.Height=430; $w.Owner=$window
    $box=New-Object Windows.Controls.TextBox; $box.Text=($logs -join [Environment]::NewLine); $box.IsReadOnly=$true; $box.AcceptsReturn=$true; $box.VerticalScrollBarVisibility='Auto'; $box.FontFamily='Cascadia Mono'; $box.Background='#122033'; $box.Foreground='#D9E5F3'; $box.Padding='10'; $w.Content=$box; [void]$w.ShowDialog()
})
[void](Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class AnsaAutoMeshConsole {
    [DllImport("kernel32.dll")] public static extern IntPtr GetConsoleWindow();
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr handle, int command);
}
'@ -ErrorAction SilentlyContinue)
$window.Add_ContentRendered({
    $console = [AnsaAutoMeshConsole]::GetConsoleWindow()
    if ($console -ne [IntPtr]::Zero) { [void][AnsaAutoMeshConsole]::ShowWindow($console, 0) }
})
$timer.Start()
[void]$window.ShowDialog()
