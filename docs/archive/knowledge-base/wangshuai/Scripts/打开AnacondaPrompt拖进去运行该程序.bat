@echo off
echo ============================================
echo Fixing aria2c Path Issue
echo ============================================
echo.

REM Activate conda environment
call conda activate SBD_env
if %ERRORLEVEL% NEQ 0 (
    echo Error: Failed to activate SBD_env environment
    echo Please check if the environment exists
    pause
    exit /b 1
)

echo Successfully activated SBD_env environment
echo.

REM Uninstall aria2 related packages
echo Uninstalling aria2 related packages...
pip uninstall aria2 aria2c -y
if %ERRORLEVEL% NEQ 0 (
    echo Warning: Error during uninstall, continuing...
)

echo.

REM Install aria2
echo Installing aria2...
pip install aria2
if %ERRORLEVEL% NEQ 0 (
    echo Error: aria2 installation failed
    pause
    exit /b 1
)

echo.
echo ============================================
echo Fix completed!
echo Please test with: aria2c --version
echo ============================================
pause