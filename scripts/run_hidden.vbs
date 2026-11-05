' Hidden StudyOnPC watchdog (relaunches main). Prefer StudyOnPC.exe; else pythonw.
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
root = fso.GetParentFolderName(dir)
sh.CurrentDirectory = root
logs = root & "\logs"
If Not fso.FolderExists(logs) Then fso.CreateFolder(logs)
stopFlag = logs & "\stop.flag"
If fso.FileExists(stopFlag) Then fso.DeleteFile stopFlag, True
exe = root & "\StudyOnPC.exe"
If fso.FileExists(exe) Then
  sh.Run """" & exe & """ --role=watchdog", 0, False
Else
  cmd = "pythonw.exe """ & root & "\studyonpc.py"" --role=watchdog"
  sh.Run cmd, 0, False
End If
