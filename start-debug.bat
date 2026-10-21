@echo off
rem Start with a console window that prints every detected shake.
setlocal
call "%~dp0_findpy.bat"
if not defined PYEXE goto nopython
chcp 65001 >nul
title Shake-to-Find-Cursor (debug)
"%PYEXE%" -X utf8 "%~dp0shake_cursor.pyw" --console
echo.
echo [exited]
pause
exit /b 0

:nopython
chcp 65001 >nul
echo.
echo   Python 3.8+ was not found on this computer.
echo   Install it from https://www.python.org/downloads/
echo.
pause
exit /b 1
