@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo  Compilando "Resultados del bot de cobranza"...
echo.
where python >nul 2>nul
if errorlevel 1 (
  echo  No se encontro Python. Instala Python 3.12 desde python.org
  echo  y marca la casilla "Add python.exe to PATH" durante la instalacion.
  pause
  exit /b 1
)
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
  echo  No se pudieron instalar las librerias. Revisa la conexion a internet o el proxy de la empresa.
  pause
  exit /b 1
)
pyinstaller --noconfirm --clean --onefile --windowed --name "ResultadosBot" --icon "icono.ico" --add-data "app;app" main.py
if errorlevel 1 (
  echo  La compilacion fallo. Revisa los mensajes de arriba.
  pause
  exit /b 1
)
echo.
echo  Listo. El ejecutable esta en: dist\ResultadosBot.exe
echo.
explorer dist
pause
