@echo off
rem Troubleshooting launcher — runs the app WITH a console window so you can
rem see server output and error messages. For normal use, run.bat (no window).
cd /d "%~dp0"
echo Starting Club Training (debug mode - console stays open)...
python app.py
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Could not start the app.
    echo Make sure Python is installed and you have run install.bat first.
    pause
)
