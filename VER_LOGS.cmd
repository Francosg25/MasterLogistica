@echo off
setlocal
call "%~dp0scripts\local.cmd" logs %*
set "local_result=%ERRORLEVEL%"
pause
exit /b %local_result%
