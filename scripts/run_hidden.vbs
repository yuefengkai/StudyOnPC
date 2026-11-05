' 无窗口启动看门狗（会再拉起主程序）；优先 StudyOnPC.exe
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
root = fso.GetParentFolderName(dir)
exe = root & "\StudyOnPC.exe"
If fso.FileExists(exe) Then
  sh.Run """" & exe & """ --role=watchdog", 0, False
Else
  cmd = "pythonw.exe """ & root & "\studyonpc.py"" --role=watchdog"
  sh.Run cmd, 0, False
End If
