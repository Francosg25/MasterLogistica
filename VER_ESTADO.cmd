@echo off
setlocal
call "%~dp0scripts\local.cmd" status %*
set "local_result=%ERRORLEVEL%"
pause
exit /b %local_result%
