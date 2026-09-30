@echo off
rem Start the home in the background (no windows). Friend requests and batch runs keep going without the screen.
rem To see the screen, run start.bat as usual (it connects to the running home). To stop it, use the screen's stop-all button.
rem Details: home\README.txt
wscript //nologo "%~dp0home\start_hidden.vbs"
