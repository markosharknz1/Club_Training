@echo off
cd /d "%~dp0"
echo Building standalone Club Training executable...
echo.

pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing PyInstaller (build tool, one-time)...
    pip install pyinstaller
    if %errorlevel% neq 0 (
        echo ERROR: could not install PyInstaller.
        pause
        exit /b 1
    )
)

pyinstaller --noconfirm --clean --windowed --name Club_Training ^
    --icon "static\icon.ico" ^
    --add-data "templates;templates" ^
    --add-data "static;static" ^
    --hidden-import webview.platforms.edgechromium ^
    --hidden-import webview.platforms.winforms ^
    app.py

if %errorlevel% neq 0 (
    echo.
    echo ERROR: build failed - see output above.
    pause
    exit /b 1
)

echo.
echo Done! The standalone app is in:  dist\Club_Training\
echo Give that whole folder to someone (zip or USB) - they double-click
echo Club_Training.exe inside it. No Python needed on their machine.
echo The database (badminton.db) is created next to the exe on first run;
echo copy an existing badminton.db into that folder to bring club data along.
pause
