@echo off
setlocal
cd /d "%~dp0"

title Rebelion Stock v2

echo ============================================
echo        INICIANDO REBELION STOCK v2
echo ============================================
echo.

REM Buscar una instalacion de Python valida.
where py >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON=py -3"
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        set "PYTHON=python"
    ) else (
        echo ERROR: No se encontro Python instalado.
        echo.
        echo Instala Python 3 desde python.org y volve a ejecutar este archivo.
        echo IMPORTANTE: durante la instalacion marca "Add Python to PATH".
        echo.
        pause
        exit /b 1
    )
)

echo Python encontrado.

echo.

REM Crear un entorno virtual local para no depender de paquetes globales.
if not exist ".venv\Scripts\python.exe" (
    echo Preparando el entorno de Rebelion Stock por primera vez...
    %PYTHON% -m venv .venv
    if errorlevel 1 goto :venv_error
)

set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"

REM Instalar dependencias solamente si faltan.
"%VENV_PYTHON%" -c "import flask, openpyxl, waitress" >nul 2>nul
if errorlevel 1 (
    echo Instalando dependencias necesarias...
    echo Esto se realiza solo la primera vez.
    echo.
    "%VENV_PYTHON%" -m pip install -r requirements.txt
    if errorlevel 1 goto :pip_error
    echo.
)

echo Iniciando servidor Waitress para tu PC y la red local...
echo.
echo IMPORTANTE: si Windows Firewall pregunta, permiti el acceso en
 echo "Redes privadas" para que otras personas de tu misma red puedan entrar.
echo.
"%VENV_PYTHON%" app.py
set "APP_ERROR=%errorlevel%"

echo.
if not "%APP_ERROR%"=="0" (
    echo ============================================
    echo ERROR AL INICIAR REBELION STOCK
    echo Codigo de salida: %APP_ERROR%
    echo ============================================
    echo.
) else (
    echo Rebelion Stock se cerro correctamente.
)
pause
exit /b %APP_ERROR%

:venv_error
echo.
echo ERROR: No se pudo crear el entorno de Python.
echo Verifica que Python este instalado correctamente.
pause
exit /b 1

:pip_error
echo.
echo ERROR: No se pudieron instalar las dependencias.
echo Verifica tu conexion a Internet y volve a ejecutar el archivo.
echo Si seguira fallando, copia y pega aqui el mensaje completo.
pause
exit /b 1
