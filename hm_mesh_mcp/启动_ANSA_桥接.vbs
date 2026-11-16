Option Explicit

Dim shell, fso, launcherDir, app, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

launcherDir = fso.GetParentFolderName(WScript.ScriptFullName)
app = fso.BuildPath(launcherDir, "ANSA Auto Mesh BRIDGE.ps1")
shell.CurrentDirectory = launcherDir

If Not fso.FileExists(app) Then
    MsgBox "Cannot find ANSA Auto Mesh BRIDGE.ps1:" & vbCrLf & app, vbCritical, "ANSA Bridge"
    WScript.Quit 1
End If

command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -Command " & Chr(34) & _
          "try { & '" & Replace(app, "'", "''") & "' } catch { Add-Type -AssemblyName PresentationFramework; " & _
          "[System.Windows.MessageBox]::Show(($_ | Out-String), 'ANSA Bridge Failed') | Out-Null }" & Chr(34)

shell.Run command, 1, False
