' Start the home (launcher) in the background: no browser window, no console window.
' Used by start-background.bat and by a shortcut in the Startup folder (shell:startup).
' Details: src\home\README.txt (section "background"). If the home is already running, launch.py just exits.
Option Explicit
Dim fso, sh, root, py
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
' This file is in src\home\, so the repository root is three levels up.
root = fso.GetParentFolderName(fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName)))
sh.CurrentDirectory = root
' Same choice of Python as start.bat: py -3.10 first, then the py launcher, then python on PATH.
If sh.Run("cmd /c py -3.10 --version >nul 2>&1", 0, True) = 0 Then
  py = "py -3.10"
ElseIf sh.Run("cmd /c py -3 --version >nul 2>&1", 0, True) = 0 Then
  py = "py -3"
ElseIf sh.Run("cmd /c python --version >nul 2>&1", 0, True) = 0 Then
  py = "python"
Else
  MsgBox "Python 3 was not found. Install it, then try again.", 48, "youtube-tools"
  WScript.Quit 1
End If
' Window style 0 = hidden. The tools started by the launcher share this hidden console.
sh.Run "cmd /c " & py & " src\home\launch.py --no-open", 0, False
