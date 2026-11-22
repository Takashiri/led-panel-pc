@echo off
setlocal
set "LED_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%LED_PYTHON%" (
    echo Chybi prostredi .venv. Postup instalace najdes v README.md.
    pause
    exit /b 1
)
"%LED_PYTHON%" -X utf8 "%~dp0pc_status.py" %*
set "LED_EXIT=%errorlevel%"
if not "%LED_EXIT%"=="0" if "%~1"=="" pause
exit /b %LED_EXIT%
