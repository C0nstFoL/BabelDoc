$ErrorActionPreference = "Stop"

$AppName = "BabelDOC"
$AppFile = "babeldoc_translator.py"
$PidFile = ".babeldoc-windows.pid"
$LogDir = "logs"
$LogFile = Join-Path $LogDir "babeldoc-windows.log"
$Port = 7865

Set-Location $PSScriptRoot

function Get-Python {
    $venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return $venvPython
    }
    $python = Get-Command py -ErrorAction SilentlyContinue
    if ($python) {
        return $python.Source
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return $python.Source
    }
    throw "未找到 Python。请安装 Python 3.10+ 并将其加入 PATH。"
}

function Get-AppProcess {
    if (-not (Test-Path $PidFile)) {
        return $null
    }
    $pid = Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pid -and ($process = Get-Process -Id ([int]$pid) -ErrorAction SilentlyContinue)) {
        return $process
    }
    return $null
}

function Install-Dependencies($python) {
    & $python -c "import gradio" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "正在安装 Python 依赖..." -ForegroundColor Yellow
        & $python -m pip install -r requirements.txt
    }
}

function Start-App {
    $existing = Get-AppProcess
    if ($existing) {
        Write-Host "$AppName 已在运行中 (PID: $($existing.Id))" -ForegroundColor Yellow
        return
    }

    $python = Get-Python
    Install-Dependencies $python
    New-Item -ItemType Directory -Force $LogDir | Out-Null

    $process = Start-Process -FilePath $python `
        -ArgumentList $AppFile `
        -WorkingDirectory $PSScriptRoot `
        -RedirectStandardOutput $LogFile `
        -RedirectStandardError $LogFile `
        -PassThru
    Set-Content -Path $PidFile -Value $process.Id
    Start-Sleep -Seconds 2

    if (Get-AppProcess) {
        Write-Host "$AppName 已启动 (PID: $($process.Id))" -ForegroundColor Green
        Write-Host "访问地址: http://localhost:$Port"
        Write-Host "查看日志: .\start.ps1 logs"
    } else {
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
        throw "启动失败，请查看 $LogFile"
    }
}

function Stop-App {
    $process = Get-AppProcess
    if (-not $process) {
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
        Write-Host "$AppName 当前未运行" -ForegroundColor Yellow
        return
    }
    Stop-Process -Id $process.Id -Force
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    Write-Host "$AppName 已停止" -ForegroundColor Green
}

function Show-Status {
    $process = Get-AppProcess
    if ($process) {
        Write-Host "状态: 运行中" -ForegroundColor Green
        Write-Host "PID: $($process.Id)"
        Write-Host "访问地址: http://localhost:$Port"
        Write-Host "日志: $LogFile"
    } else {
        Write-Host "状态: 未运行" -ForegroundColor Yellow
    }
}

function Show-Logs {
    if (-not (Test-Path $LogFile)) {
        Write-Host "日志文件不存在: $LogFile" -ForegroundColor Yellow
        return
    }
    Get-Content -Path $LogFile -Wait
}

$command = if ($args.Count -gt 0) { $args[0].ToLowerInvariant() } else { "help" }
switch ($command) {
    "start" { Start-App }
    "stop" { Stop-App }
    "restart" { Stop-App; Start-App }
    "status" { Show-Status }
    "logs" { Show-Logs }
    default {
        Write-Host "用法: .\start.ps1 {start|stop|restart|status|logs}"
    }
}
