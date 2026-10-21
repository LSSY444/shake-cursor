@echo off
rem Quit the running instance and force-restore the system mouse cursor.
rem Use this if the pointer ever becomes invisible.
setlocal
call "%~dp0_findpy.bat"
if not defined PYEXE goto nopython
chcp 65001 >nul
"%PYEXE%" -X utf8 "%~dp0stop.py"
timeout /t 2 >nul
exit /b 0

:nopython
chcp 65001 >nul
echo python.exe not found - restoring the cursor via PowerShell instead...
powershell -NoProfile -Command "Add-Type -Namespace W -Name N -MemberDefinition '[DllImport(\"user32.dll\")] public static extern bool SystemParametersInfo(int a,int b,System.IntPtr c,int d);'; [W.N]::SystemParametersInfo(0x57,0,[IntPtr]::Zero,2)" >nul 2>&1
echo Cursor restored.
pause
exit /b 0
