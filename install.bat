@echo off
echo Installing Badminton Club requirements...
echo.
pip install -r requirements.txt
echo.
if %errorlevel% neq 0 (
    echo ERROR: pip install failed. Make sure Python is installed and in your PATH.
    pause
    exit /b 1
)
echo All done! Run run.bat to start the app.
pause
