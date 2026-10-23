@echo off
setlocal
call "%~dp0scripts\local.cmd" start %*
set "local_result=%ERRORLEVEL%"
if not "%local_result%"=="0" pause
exit /b %local_result%
