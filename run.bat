@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

set "EXIT_CODE=0"

echo ============================================================
REM Sin tilde: este .bat no fija codepage y cmd lo leeria con la del sistema.
echo  Taller de Rotulacion
echo ============================================================
echo.

REM --- Verificar Python ---
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python no esta en el PATH.
    echo Instala Python 3.10+ desde https://www.python.org/downloads/
    echo Durante la instalacion marca "Add Python to PATH".
    echo.
    set "EXIT_CODE=1"
    goto :end
)

REM --- Crear/activar venv ---
if not exist ".venv\Scripts\python.exe" (
    echo [+] Creando entorno virtual...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] No se pudo crear el entorno virtual.
        set "EXIT_CODE=1"
        goto :end
    )
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo [ERROR] No se pudo activar el entorno virtual.
    set "EXIT_CODE=1"
    goto :end
)

REM --- Instalar dependencias ---
echo [+] Verificando dependencias...
python -m pip install --upgrade pip >nul 2>&1
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] No se pudieron instalar las dependencias.
    set "EXIT_CODE=1"
    goto :end
)

REM --- Preparar carpeta de logs ---
if not exist "logs" mkdir "logs"

REM --- Aviso sobre Tesseract (no es necesario para abrir el programa) ---
where tesseract >nul 2>&1
if errorlevel 1 (
    if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" (
        echo [i] Tesseract detectado en C:\Program Files\Tesseract-OCR
    ) else if exist "C:\Program Files (x86)\Tesseract-OCR\tesseract.exe" (
        echo [i] Tesseract detectado en C:\Program Files ^(x86^)\Tesseract-OCR
    ) else (
        echo [i] Tesseract no encontrado. OCR deshabilitado hasta instalarlo.
        echo     Para habilitar OCR: winget install UB-Mannheim.TesseractOCR
    )
) else (
    echo [i] Tesseract disponible en PATH.
)

echo.
echo [+] Iniciando aplicacion...
echo     Logs: %CD%\logs\app.log
echo     Cierra la ventana o usa el boton Inicio para salir.
echo.

REM --- Lanzar la app ---
python main.py
set "EXIT_CODE=%errorlevel%"

:end
if not "%EXIT_CODE%"=="0" (
    echo.
    echo ============================================================
    echo  La aplicacion finalizo con un error ^(codigo %EXIT_CODE%^).
    echo  Revisa el log: %CD%\logs\app.log
    echo ============================================================
)

endlocal & exit /b %EXIT_CODE%
