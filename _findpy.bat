@echo off
rem ---------------------------------------------------------------------------
rem  Locate a Python interpreter and return its full path in %PYEXE%.
rem  Usage:  call _findpy.bat        -> python.exe
rem          call _findpy.bat w      -> pythonw.exe (no console window)
rem  No hardcoded usernames or version folders: it probes the usual install
rem  roots, then PATH, then the "py" launcher.
rem ---------------------------------------------------------------------------
set "PYEXE="
if /i "%~1"=="w" (set "EXENAME=pythonw.exe") else (set "EXENAME=python.exe")

rem 1) usual install roots (per-user python.org installer / all-users installer)
for %%R in ("%LOCALAPPDATA%\Programs\Python" "%ProgramFiles%" "%ProgramFiles(x86)%") do (
    for %%V in (314 313 312 311 310 39 38) do (
        if not defined PYEXE if exist "%%~R\Python%%V\%EXENAME%" set "PYEXE=%%~R\Python%%V\%EXENAME%"
    )
)

rem 2) whatever comes first on PATH
if not defined PYEXE for /f "delims=" %%i in ('where %EXENAME% 2^>nul') do (
    if not defined PYEXE set "PYEXE=%%i"
)

rem 3) last resort: ask the py launcher where python.exe lives
if not defined PYEXE call :via_launcher
exit /b 0

:via_launcher
set "TMPTXT=%TEMP%\_findpy_exe.txt"
py -3 -c "import sys;print(sys.executable)" > "%TMPTXT%" 2>nul
if not exist "%TMPTXT%" exit /b 0
for /f "usebackq delims=" %%i in ("%TMPTXT%") do set "PYEXE=%%i"
del "%TMPTXT%" 2>nul
if not defined PYEXE exit /b 0
if /i "%~1"=="w" (set "PYEXE=%PYEXE:python.exe=pythonw.exe%")
if not exist "%PYEXE%" set "PYEXE="
exit /b 0
