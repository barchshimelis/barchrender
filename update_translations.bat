@echo off
setlocal

:: Set the full path to gettext
set "GETTEXT_BIN=C:\Program Files\gettext\bin"
set "PATH=%GETTEXT_BIN%;%PATH%"

:: Verify msguniq is found
where msguniq >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Error: msguniq not found in %GETTEXT_BIN%
    echo Please verify gettext is installed correctly.
    pause
    exit /b 1
)

echo Creating locale directory...
if not exist "locale" mkdir locale

echo.
echo Generating translation files...
python manage.py makemessages -l en

if %ERRORLEVEL% EQU 0 (
    echo.
    echo Translation files created successfully!
    echo.
    echo Next steps:
    echo 1. Edit the .po file in locale\en\LC_MESSAGES\django.po
    echo 2. Run: python manage.py compilemessages
) else (
    echo.
    echo Failed to create translation files.
)

pause