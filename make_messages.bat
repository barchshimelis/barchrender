@echo off
setlocal enabledelayedexpansion

:: Set the full path to gettext
set "GETTEXT_BIN=C:\Program Files\gettext\bin"
set "PATH=%GETTEXT_BIN%;%PATH%"

set LANGUAGES=en zh_Hans hi es fr ar bn ru pt id ur de ja tr ko it nl pl vi th ku az

for %%L in (%LANGUAGES%) do (
    echo Creating messages for %%L...
    python manage.py makemessages -l %%L
)

echo.
echo All message files have been created in the 'locale' directory.
echo.
echo Next steps:
echo 1. Edit the .po files in locale/LC_MESSAGES/
echo 2. Run: python manage.py compilemessages
echo.
pause