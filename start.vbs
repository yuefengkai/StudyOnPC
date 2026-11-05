' StudyOnPC hidden launcher (double-click — no black window)
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = root
sh.Run "wscript.exe //nologo """ & root & "\scripts\run_hidden.vbs""", 0, False
