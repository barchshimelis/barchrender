@echo off
setlocal

:: Set the full path to gettext
set "GETTEXT_BIN=C:\Program Files\gettext\bin"
set "PATH=%GETTEXT_BIN%;%PATH%"

:: Verify msgfmt is found
where msgfmt >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Error: msgfmt not found in %GETTEXT_BIN%
    echo Please verify gettext is installed correctly.
    pause
    exit /b 1
)

echo Compiling message files...
python manage.py compilemessages

if %ERRORLEVEL% EQU 0 (
    echo.
    echo Message files compiled successfully!
) else (
    echo.
    echo Failed to compile message files.
)

pause