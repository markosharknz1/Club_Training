@echo off
rem Starts Club Training via the bundled, python.org-signed pythonw.exe.
rem No console window stays open — pythonw is a windowless program.
start "" "%~dp0python\pythonw.exe" "%~dp0launch.py"
