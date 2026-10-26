@echo off
setlocal
pushd "%~dp0.."
where py >nul 2>nul
if errorlevel 1 goto use_python
py -3 scripts\local_dev.py %*
goto finished
:use_python
python scripts\local_dev.py %*
:finished
set "local_exit=%ERRORLEVEL%"
popd
if not "%local_exit%"=="0" (
    echo.
    echo No se completo la operacion. Revisa el mensaje anterior y .local-dev\local.log.
    echo Inicio directo: Python 3.11 o posterior y Node compatible con Angular 21.
    echo Docker solo se requiere cuando se selecciona --mode docker.
)
exit /b %local_exit%
