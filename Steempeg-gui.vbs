' Launch Steempeg without a console window (pythonw).
' Double-click this, or pin a shortcut to it.
Option Explicit
Dim sh, fso, root, pyw, script
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
pyw = root & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(pyw) Then pyw = "pythonw.exe"
script = root & "\steempeg\app.py"
sh.CurrentDirectory = root
' 0 = hidden window, False = do not wait
sh.Run """" & pyw & """ """ & script & """", 0, False
