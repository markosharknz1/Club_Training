@echo off
cd /d "%~dp0"
echo Installing Club Training requirements...
echo.

echo Trying offline install first (using the bundled packages in vendor_wheels)...
pip install --no-index --find-links=vendor_wheels -r requirements.txt >nul 2>&1
if %errorlevel% equ 0 (
    echo Offline install succeeded - no internet was needed for the Python packages.
    goto :webview2check
)

echo Offline install didn't work for this machine's Python version - trying an online install instead...
echo.
pip install -r requirements.txt
echo.
if %errorlevel% neq 0 (
    echo ERROR: pip install failed. Make sure Python is installed and in your PATH,
    echo and that you have an internet connection for this fallback install.
    pause
    exit /b 1
)

:webview2check
echo.
echo Checking for the Microsoft Edge WebView2 Runtime (needed for the app's window)...
set WV2_FOUND=0
reg query "HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" >nul 2>&1 && set WV2_FOUND=1
reg query "HKLM\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" >nul 2>&1 && set WV2_FOUND=1
reg query "HKCU\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" >nul 2>&1 && set WV2_FOUND=1

if "%WV2_FOUND%"=="1" (
    echo WebView2 Runtime already present - nothing to do.
) else (
    echo WebView2 Runtime not found - installing it now using the bundled installer...
    vendor_installers\MicrosoftEdgeWebview2Setup.exe /silent /install
    echo WebView2 Runtime installed.
)

echo.
echo All done! Run run.bat to start the app.
pause
