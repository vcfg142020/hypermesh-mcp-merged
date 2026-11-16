Option Explicit

' Double-click launcher for the standalone HyperMesh background meshing panel.
' Keep this file ASCII-only so Windows Script Host will not misread encoding.

Dim shell, fso, launcherDir, projectRoot, scriptPath, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

launcherDir = fso.GetParentFolderName(WScript.ScriptFullName)
projectRoot = fso.GetParentFolderName(launcherDir)
scriptPath = fso.BuildPath(projectRoot, "run_batch_meshing_panel.py")
shell.CurrentDirectory = projectRoot

If Not fso.FileExists(scriptPath) Then
    MsgBox "Cannot find run_batch_meshing_panel.py:" & vbCrLf & scriptPath, vbCritical, "HyperMesh Panel"
    WScript.Quit 1
End If

If CommandExists("pyw.exe") Then
    command = "pyw.exe -3 " & Quote(scriptPath)
ElseIf CommandExists("pythonw.exe") Then
    command = "pythonw.exe " & Quote(scriptPath)
ElseIf CommandExists("py.exe") Then
    command = "py.exe -3 " & Quote(scriptPath)
ElseIf CommandExists("python.exe") Then
    command = "python.exe " & Quote(scriptPath)
Else
    MsgBox "Cannot find Python launcher. Please install Python or add py.exe/python.exe to PATH.", vbCritical, "HyperMesh Panel"
    WScript.Quit 2
End If

shell.Run command, 0, False

Function Quote(value)
    Quote = Chr(34) & value & Chr(34)
End Function

Function CommandExists(name)
    Dim code
    code = shell.Run("cmd.exe /c where " & name & " >nul 2>nul", 0, True)
    CommandExists = (code = 0)
End Function
