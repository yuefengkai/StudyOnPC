' Hidden StudyOnPC watchdog (relaunches main).
' Prefer pythonw + studyonpc.py so source updates apply without rebuilding exe.
' Fall back to StudyOnPC.exe only when pythonw is unavailable.
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
root = fso.GetParentFolderName(dir)
sh.CurrentDirectory = root
logs = root & "\logs"
If Not fso.FolderExists(logs) Then fso.CreateFolder(logs)
stopFlag = logs & "\stop.flag"
If fso.FileExists(stopFlag) Then fso.DeleteFile stopFlag, True

pyw = ""
candidates = Array( _
  "D:\anaconda3\pythonw.exe", _
  "C:\Python312\pythonw.exe", _
  "C:\Python311\pythonw.exe" _
)
For Each c In candidates
  If fso.FileExists(c) Then
    pyw = c
    Exit For
  End If
Next

If pyw <> "" Then
  cmd = """" & pyw & """ """ & root & "\studyonpc.py"" --role=watchdog"
  sh.Run cmd, 0, False
Else
  On Error Resume Next
  sh.Run "pythonw.exe """ & root & "\studyonpc.py"" --role=watchdog", 0, False
  If Err.Number <> 0 Then
    Err.Clear
    exe = root & "\StudyOnPC.exe"
    If fso.FileExists(exe) Then
      sh.Run """" & exe & """ --role=watchdog", 0, False
    Else
      distExe = root & "\dist\StudyOnPC\StudyOnPC.exe"
      If fso.FileExists(distExe) Then
        sh.Run """" & distExe & """ --role=watchdog", 0, False
      End If
    End If
  End If
  On Error GoTo 0
End If
