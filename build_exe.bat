@echo off
setlocal

rem =========================================================
rem Build script para gerar o executavel .exe com PyInstaller
rem =========================================================

set "APP_SCRIPT=hz_power_switcher.py"
set "APP_ICON=hz_power_switcher.ico"
set "EXE_NAME=HzApp"
set "PYTHON_CMD=python"

if exist ".venv\Scripts\python.exe" (
  set "PYTHON_CMD=.venv\Scripts\python.exe"
)

echo ========================================
echo  Hz Power Switcher - Build para .exe
echo ========================================
echo.

rem 1) Confirmar Python
"%PYTHON_CMD%" --version >nul 2>&1
if errorlevel 1 (
  echo [ERRO] Python nao encontrado no PATH.
  echo Instala o Python 3 e marca a opcao "Add Python to PATH".
  goto :build_fail
)

rem 2) Confirmar script principal
if not exist "%APP_SCRIPT%" (
  echo [ERRO] Ficheiro "%APP_SCRIPT%" nao encontrado.
  echo Executa este .bat na pasta do projeto.
  goto :build_fail
)

rem 3) Garantir pip atualizado e pyinstaller instalado
echo [INFO] A verificar/instalar PyInstaller...
"%PYTHON_CMD%" -m ensurepip --upgrade >nul 2>&1
"%PYTHON_CMD%" -m pip install --upgrade pip >nul 2>&1
"%PYTHON_CMD%" -m pip install --upgrade pyinstaller
if errorlevel 1 (
  echo [ERRO] Nao foi possivel instalar/atualizar o PyInstaller.
  goto :build_fail
)

rem 4) Encerrar instancias abertas do exe (evita WinError 5 / Acesso negado)
tasklist /FI "IMAGENAME eq %EXE_NAME%.exe" 2>nul | find /I "%EXE_NAME%.exe" >nul
if not errorlevel 1 (
  echo [INFO] A encerrar instancias de %EXE_NAME%.exe para permitir a conversao...
  taskkill /F /IM "%EXE_NAME%.exe" >nul 2>&1
)

rem 5) Limpeza opcional de builds antigos
if exist "build" rmdir /s /q "build"
if exist "dist\%EXE_NAME%.exe" del /q "dist\%EXE_NAME%.exe"

rem 6) Build com ou sem icone
if exist "%APP_ICON%" (
  echo [INFO] Icone encontrado: %APP_ICON%
  "%PYTHON_CMD%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
      --add-data "hz_power_switcher.ico;." ^
      --hidden-import pystray ^
      --hidden-import PIL.Image ^
      --hidden-import PIL.ImageDraw ^
      --hidden-import PIL.ImageFont ^
    --name "%EXE_NAME%" ^
    --icon "%APP_ICON%" ^
    "%APP_SCRIPT%"
) else (
  echo [AVISO] Icone "%APP_ICON%" nao encontrado. Build sera feito sem icone.
  "%PYTHON_CMD%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
      --add-data "hz_power_switcher.ico;." ^
      --hidden-import pystray ^
      --hidden-import PIL.Image ^
      --hidden-import PIL.ImageDraw ^
      --hidden-import PIL.ImageFont ^
    --name "%EXE_NAME%" ^
    "%APP_SCRIPT%"
)

if errorlevel 1 (
  echo [ERRO] Falha no build do executavel.
  goto :build_fail
)

echo.
echo [OK] Build concluido com sucesso.
echo Executavel gerado em: dist\%EXE_NAME%.exe
echo.
echo Dica: para testar, executa:
echo   dist\%EXE_NAME%.exe
echo.
echo Prima qualquer tecla para fechar...
pause >nul
exit /b 0

:build_fail
echo.
echo Prima qualquer tecla para fechar...
pause >nul
exit /b 1
