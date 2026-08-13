@echo off
REM build_launcher.bat -- Compile DorianCoinLauncher.exe from source
REM Run this from the repo root: .\build_launcher.bat

echo.
echo  ================================================================
echo   DorianCoin Launcher -- Build Script
echo  ================================================================
echo.

REM 1. Ensure PyInstaller is installed
python -m pip install --quiet pyinstaller
if errorlevel 1 (
    echo  [ERROR] Could not install PyInstaller. Aborting.
    pause
    exit /b 1
)

REM 2. Clean previous build artefacts
if exist build\DorianCoinLauncher  rmdir /s /q build\DorianCoinLauncher
if exist dist\DorianCoinLauncher.exe  del /f /q dist\DorianCoinLauncher.exe

REM 3. Compile
echo  Building DorianCoinLauncher.exe ...
python -m PyInstaller --clean --noconfirm DorianCoinLauncher.spec

if errorlevel 1 (
    echo.
    echo  [ERROR] Build failed. Check output above.
    pause
    exit /b 1
)

echo.
echo  ================================================================
echo   Build complete!
echo   EXE: dist\DorianCoinLauncher.exe
echo  ================================================================
echo.
echo  Double-click dist\DorianCoinLauncher.exe to launch DorianCoin.
echo.
pause
