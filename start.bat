@echo off
setlocal EnableExtensions

set "APP_NAME=BabelDOC"
set "APP_FILE=babeldoc_translator.py"
set "PID_FILE=.babeldoc-windows.pid"
set "LOG_DIR=logs"
set "LOG_FILE=%LOG_DIR%\babeldoc-windows.log"
set "ERROR_LOG_FILE=%LOG_DIR%\babeldoc-windows-error.log"
set "PORT=7865"

cd /d "%~dp0"

if /i "%~1"=="start" goto start_app
if /i "%~1"=="stop" goto stop_app
if /i "%~1"=="restart" goto restart_app
if /i "%~1"=="status" goto status_app
if /i "%~1"=="logs" goto logs_app
goto help

:find_python
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON=%~dp0.venv\Scripts\python.exe"
    set "PYTHON_ARGS="
    exit /b 0
)
where py >nul 2>&1
if not errorlevel 1 (
    set "PYTHON=py.exe"
    set "PYTHON_ARGS=-3"
    exit /b 0
)
where python >nul 2>&1
if not errorlevel 1 (
    set "PYTHON=python.exe"
    set "PYTHON_ARGS="
    exit /b 0
)
echo [错误] 未找到 Python 3.10+，请先安装 Python 并将其加入 PATH。
exit /b 1

:check_process
if not exist "%PID_FILE%" exit /b 1
set /p APP_PID=<"%PID_FILE%"
if not defined APP_PID exit /b 1
tasklist /fi "PID eq %APP_PID%" /fo csv /nh | findstr /r /c:"%APP_PID%" >nul
if errorlevel 1 exit /b 1
exit /b 0

:start_app
call :check_process
if not errorlevel 1 (
    echo [提示] %APP_NAME% 已在运行中，PID: %APP_PID%
    exit /b 0
)
call :find_python
if errorlevel 1 exit /b 1
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
"%PYTHON%" -c "import gradio" >nul 2>&1
if errorlevel 1 (
    echo [提示] 正在安装 Python 依赖...
    "%PYTHON%" -m pip install -r requirements.txt
    if errorlevel 1 exit /b 1
)
start "BabelDOC" /b cmd /c ""%PYTHON%" %PYTHON_ARGS% "%APP_FILE%" >> "%CD%\%LOG_FILE%" 2>> "%CD%\%ERROR_LOG_FILE%""
for /f "tokens=2 delims=," %%A in ('tasklist /v /fi "imagename eq cmd.exe" /fo csv /nh ^| findstr /i "BabelDOC"') do set "APP_PID=%%~A"
if not defined APP_PID (
    echo [错误] 启动失败，请检查 %LOG_FILE% 和 %ERROR_LOG_FILE%
    exit /b 1
)
>"%PID_FILE%" echo %APP_PID%
timeout /t 2 /nobreak >nul
call :check_process
if errorlevel 1 (
    del /q "%PID_FILE%" >nul 2>&1
    echo [错误] 启动失败，请检查 %LOG_FILE% 和 %ERROR_LOG_FILE%
    exit /b 1
)
echo [成功] %APP_NAME% 已启动，PID: %APP_PID%
echo 访问地址: http://localhost:%PORT%
echo 查看日志: start.bat logs
exit /b 0

:stop_app
call :check_process
if errorlevel 1 (
    del /q "%PID_FILE%" >nul 2>&1
    echo [提示] %APP_NAME% 当前未运行
    exit /b 0
)
taskkill /pid %APP_PID% /t /f >nul 2>&1
del /q "%PID_FILE%" >nul 2>&1
echo [成功] %APP_NAME% 已停止
exit /b 0

:restart_app
call :stop_app
call :start_app
exit /b %errorlevel%

:status_app
call :check_process
if errorlevel 1 (
    echo 状态: 未运行
) else (
    echo 状态: 运行中
    echo PID: %APP_PID%
    echo 访问地址: http://localhost:%PORT%
    echo 日志: %LOG_FILE%
)
exit /b 0

:logs_app
if not exist "%LOG_FILE%" (
    echo [提示] 日志文件不存在: %LOG_FILE%
    exit /b 1
)
type "%LOG_FILE%"
if exist "%ERROR_LOG_FILE%" (
    echo.
    echo ===== 错误日志 =====
    type "%ERROR_LOG_FILE%"
)
exit /b 0

:help
echo 用法: start.bat {start^|stop^|restart^|status^|logs}
exit /b 0
