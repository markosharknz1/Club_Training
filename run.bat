@echo off
cd /d "%~dp0"
echo Starting Club Training...
python app.py
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Could not start the app.
    echo Make sure Python is installed and you have run install.bat first.
    pause
)
