@echo off
rem Disable "run at login" for the current user.
setlocal
call "%~dp0_findpy.bat"
if not defined PYEXE goto nopython
chcp 65001 >nul
"%PYEXE%" -X utf8 "%~dp0autostart.py" off
echo.
pause
exit /b 0

:nopython
chcp 65001 >nul
echo python.exe not found. Install Python 3.8+ first.
pause
exit /b 1
