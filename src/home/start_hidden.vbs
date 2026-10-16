' Forwarder kept for the Startup folder shortcut (shell:startup) that still points here.
' The real file moved to src\app\start_hidden.vbs (RV, 2026-10-16). Point the shortcut there, then this file can go.
Option Explicit
Dim fso, sh, target
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
target = fso.BuildPath(fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName)), "app\start_hidden.vbs")
sh.Run "wscript //nologo """ & target & """", 0, False
