@echo off
setlocal EnableExtensions

set "APP_NAME=BabelDOC"
set "APP_FILE=babeldoc_translator.py"
set "PID_FILE=.babeldoc-windows.pid"
set "LOG_DIR=logs"
set "LOG_FILE=%CD%\%LOG_DIR%\babeldoc-windows.log"
set "ERROR_LOG_FILE=%CD%\%LOG_DIR%\babeldoc-windows-error.log"
set "PORT=7865"

cd /d "%~dp0"
set "ROOT_DIR=%CD%"
set "LOG_FILE=%ROOT_DIR%\%LOG_DIR%\babeldoc-windows.log"
set "ERROR_LOG_FILE=%ROOT_DIR%\%LOG_DIR%\babeldoc-windows-error.log"
set "PID_FILE=%ROOT_DIR%\.babeldoc-windows.pid"

if /i "%~1"=="start" goto start_app
if /i "%~1"=="stop" goto stop_app
if /i "%~1"=="restart" goto restart_app
if /i "%~1"=="status" goto status_app
if /i "%~1"=="logs" goto logs_app
if "%~1"=="" goto deploy_app
goto help

:deploy_app
echo ========================================
echo   BabelDOC Windows one-click setup
echo ========================================
echo.

if not exist "%ROOT_DIR%\.babeldoc_config.json" type nul > "%ROOT_DIR%\.babeldoc_config.json"
if not exist "%ROOT_DIR%\.babeldoc_history.json" type nul > "%ROOT_DIR%\.babeldoc_history.json"
if not exist "%ROOT_DIR%\outputs" mkdir "%ROOT_DIR%\outputs"

if not exist "%ROOT_DIR%\.venv\Scripts\python.exe" (
    where py.exe >nul 2>&1
    if not errorlevel 1 (
        echo Creating Python virtual environment...
        py.exe -3 -m venv "%ROOT_DIR%\.venv"
    ) else (
        where python.exe >nul 2>&1
        if errorlevel 1 (
            echo [ERROR] Python 3.10+ was not found. Install Python and try again.
            pause
            exit /b 1
        )
        echo Creating Python virtual environment...
        python.exe -m venv "%ROOT_DIR%\.venv"
    )
    if errorlevel 1 (
        echo [ERROR] Failed to create the virtual environment.
        pause
        exit /b 1
    )
)

call :start_app
set "DEPLOY_EXIT=%errorlevel%"
echo.
if "%DEPLOY_EXIT%"=="0" echo Open http://localhost:%PORT% in your browser.
pause
exit /b %DEPLOY_EXIT%

:find_python
if exist "%ROOT_DIR%\.venv\Scripts\python.exe" (
    set "PYTHON=%ROOT_DIR%\.venv\Scripts\python.exe"
    set "PYTHON_ARGS="
    exit /b 0
)
where py.exe >nul 2>&1
if not errorlevel 1 (
    set "PYTHON=py.exe"
    set "PYTHON_ARGS=-3"
    exit /b 0
)
where python.exe >nul 2>&1
if not errorlevel 1 (
    set "PYTHON=python.exe"
    set "PYTHON_ARGS="
    exit /b 0
)
echo [ERROR] Python 3.10+ was not found. Install Python and add it to PATH.
exit /b 1

:check_process
if not exist "%PID_FILE%" exit /b 1
set /p APP_PID=<"%PID_FILE%"
if not defined APP_PID exit /b 1
tasklist /fi "PID eq %APP_PID%" /fo csv /nh | findstr /c:"%APP_PID%" >nul
if errorlevel 1 exit /b 1
exit /b 0

:start_app
call :check_process
if not errorlevel 1 (
    echo [INFO] %APP_NAME% is already running. PID: %APP_PID%
    exit /b 0
)
call :find_python
if errorlevel 1 exit /b 1
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
"%PYTHON%" %PYTHON_ARGS% -c "import gradio, babeldoc, authlib, ocrmypdf" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing Python dependencies...
    "%PYTHON%" %PYTHON_ARGS% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install Python dependencies.
        exit /b 1
    )
)
set "BABELDOC_ROOT=%ROOT_DIR%"
set "BABELDOC_APP=%APP_FILE%"
set "BABELDOC_LOG=%LOG_FILE%"
set "BABELDOC_ERROR_LOG=%ERROR_LOG_FILE%"
set "BABELDOC_PID=%PID_FILE%"
"%PYTHON%" %PYTHON_ARGS% -c "import os,subprocess,sys; root=os.environ['BABELDOC_ROOT']; out=open(os.environ['BABELDOC_LOG'],'a',encoding='utf-8'); err=open(os.environ['BABELDOC_ERROR_LOG'],'a',encoding='utf-8'); p=subprocess.Popen([sys.executable,os.environ['BABELDOC_APP']],cwd=root,stdout=out,stderr=err,creationflags=0x08000000); open(os.environ['BABELDOC_PID'],'w').write(str(p.pid))"
if errorlevel 1 (
    echo [ERROR] Startup failed. Check %LOG_FILE% and %ERROR_LOG_FILE%
    exit /b 1
)
timeout /t 2 /nobreak >nul
call :check_process
if errorlevel 1 (
    del /q "%PID_FILE%" >nul 2>&1
    echo [ERROR] Startup failed. Check %LOG_FILE% and %ERROR_LOG_FILE%
    exit /b 1
)
echo [OK] %APP_NAME% started. PID: %APP_PID%
echo URL: http://localhost:%PORT%
echo Logs: start.bat logs
exit /b 0

:stop_app
call :check_process
if errorlevel 1 (
    del /q "%PID_FILE%" >nul 2>&1
    echo [INFO] %APP_NAME% is not running.
    exit /b 0
)
taskkill /pid %APP_PID% /t /f >nul 2>&1
del /q "%PID_FILE%" >nul 2>&1
echo [OK] %APP_NAME% stopped.
exit /b 0

:restart_app
call :stop_app
call :start_app
exit /b %errorlevel%

:status_app
call :check_process
if errorlevel 1 (
    echo Status: stopped
) else (
    echo Status: running
    echo PID: %APP_PID%
    echo URL: http://localhost:%PORT%
    echo Log: %LOG_FILE%
)
exit /b 0

:logs_app
if not exist "%LOG_FILE%" (
    echo [INFO] Log file does not exist: %LOG_FILE%
    exit /b 1
)
type "%LOG_FILE%"
if exist "%ERROR_LOG_FILE%" (
    echo.
    echo ===== Error log =====
    type "%ERROR_LOG_FILE%"
)
exit /b 0

:help
echo Usage: start.bat {start^|stop^|restart^|status^|logs}
exit /b 0
