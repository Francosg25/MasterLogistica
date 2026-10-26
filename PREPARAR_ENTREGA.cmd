@echo off
setlocal
pushd "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto use_python
py -3 scripts\build_release.py %*
goto finished
:use_python
python scripts\build_release.py %*
:finished
set "release_result=%ERRORLEVEL%"
popd
if not "%release_result%"=="0" pause
exit /b %release_result%
