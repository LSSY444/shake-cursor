@echo off
rem Start Shake-to-Find-Cursor in the background (no console window).
setlocal
call "%~dp0_findpy.bat" w
if not defined PYEXE goto nopython
start "" "%PYEXE%" -X utf8 "%~dp0shake_cursor.pyw"
exit /b 0

:nopython
chcp 65001 >nul
echo.
echo   Python 3.8+ was not found on this computer.
echo   Install it from https://www.python.org/downloads/
echo   and make sure "Add python.exe to PATH" is checked.
echo.
pause
exit /b 1
