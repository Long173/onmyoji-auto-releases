' Onmyoji Tool - silent launcher (no terminal window).
' Double-click to run. Self-locating: works from any folder.
' Logs go to logs\onmyoji_auto.log, which rotates at 5 MB (3 backups kept).
'
' pythonw.exe is launched directly rather than through cmd.exe: CreateProcess
' handles the Unicode folder name, cmd.exe does not. app.py resolves its own
' paths, so no working directory or PYTHONPATH is needed.
Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")

appDir = fso.GetParentFolderName(WScript.ScriptFullName)
entry = fso.BuildPath(appDir, "decompiled\source\app.py")

If Not fso.FileExists(entry) Then
    MsgBox "Khong tim thay: " & entry, vbCritical, "Onmyoji Tool"
    WScript.Quit 1
End If

' Window style must be 1 (normal), not 0 (hidden): the style is written into
' STARTUPINFO, and Windows applies it to the process's FIRST ShowWindow call —
' which is the one Qt makes for the main window. Style 0 hides the app itself.
' pythonw.exe allocates no console, so nothing flashes on screen anyway.
WshShell.Run "pythonw.exe """ & entry & """", 1, False
