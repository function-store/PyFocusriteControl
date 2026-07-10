@echo off
rem Toggle the Focusrite speaker/monitor mute. Shows output when run manually.
py -3 "%~dp0..\fc.py" toggle %*
