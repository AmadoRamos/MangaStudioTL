@echo off
chcp 65001 >nul
echo ===============================
echo Building Taller de Rotulacion
echo ===============================

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

set "PY=%SCRIPT_DIR%.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo ERROR: No existe %PY%
    echo Crea el entorno con: python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

REM --- PyInstaller no esta en requirements.txt: solo hace falta para esto ---
"%PY%" -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo [+] Instalando PyInstaller...
    "%PY%" -m pip install pyinstaller
    if errorlevel 1 (
        echo ERROR: No se pudo instalar PyInstaller
        pause
        exit /b 1
    )
)

if exist "dist" rmdir /s /q dist
if exist "build" rmdir /s /q build

set /p APP_VERSION=<VERSION

echo.
echo Generando ejecutable ^(unos 3 min: torch son 360 MB de DLLs^)...
echo.

"%PY%" -m PyInstaller "%SCRIPT_DIR%translator.spec" --clean --noconfirm

if %errorlevel% neq 0 (
    echo ERROR: Build fallo
    pause
    exit /b 1
)

echo.
echo Generando instalador...

set "ISCC_PATH="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC_PATH=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC_PATH if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC_PATH=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC_PATH if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC_PATH=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC_PATH if exist "%USERPROFILE%\Desktop\Inno Setup 6\ISCC.exe" set "ISCC_PATH=%USERPROFILE%\Desktop\Inno Setup 6\ISCC.exe"

if not defined ISCC_PATH (
    echo ERROR: Inno Setup no encontrado
    echo.
    echo Busca ISCC.exe en:
    echo   - %%ProgramFiles%%\Inno Setup 6\
    echo   - %%LOCALAPPDATA%%\Programs\Inno Setup 6\
    echo.
    echo Descarga desde: https://jrsoftware.org/isdl.php
    pause
    exit /b 1
)

"%ISCC_PATH%" /DAppVersion=%APP_VERSION% installer.iss

if %errorlevel% neq 0 (
    echo ERROR: Fallo al generar instalador
    pause
    exit /b 1
)

echo.
echo ===============================
echo Proceso completado
echo ===============================
echo.
echo Instalador: output\TallerRotulacion_v%APP_VERSION%_Setup.exe
echo.

pause
