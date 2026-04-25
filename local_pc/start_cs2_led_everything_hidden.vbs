\
Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")

scriptDir = FSO.GetParentFolderName(WScript.ScriptFullName)
openrgbExe = ""

If FSO.FileExists("C:\Program Files\OpenRGB\OpenRGB.exe") Then
    openrgbExe = "C:\Program Files\OpenRGB\OpenRGB.exe"
ElseIf FSO.FileExists("C:\Program Files (x86)\OpenRGB\OpenRGB.exe") Then
    openrgbExe = "C:\Program Files (x86)\OpenRGB\OpenRGB.exe"
ElseIf FSO.FileExists(WshShell.ExpandEnvironmentStrings("%LocalAppData%") & "\Programs\OpenRGB\OpenRGB.exe") Then
    openrgbExe = WshShell.ExpandEnvironmentStrings("%LocalAppData%") & "\Programs\OpenRGB\OpenRGB.exe"
End If

If openrgbExe = "" Then
    MsgBox "OpenRGB.exe was not found. Edit this VBS and set the path manually.", 16, "CS2 Local Bridge"
    WScript.Quit 1
End If

If Not FSO.FileExists(scriptDir & "\pc_local_bridge.py") Then
    MsgBox "pc_local_bridge.py was not found in: " & scriptDir, 16, "CS2 Local Bridge"
    WScript.Quit 1
End If

WshShell.Run Chr(34) & openrgbExe & Chr(34) & " --startminimized --server", 0, False
WScript.Sleep 12000
WshShell.Run "cmd /c cd /d " & Chr(34) & scriptDir & Chr(34) & " && py .\pc_local_bridge.py", 0, False

Set FSO = Nothing
Set WshShell = Nothing
