Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)

' Install deps and update silently
WshShell.Run "cmd /c cd /d """ & dir & """ && pip install --quiet google-auth google-auth-oauthlib google-api-python-client anthropic httplib2 PySocks", 0, True

' Update app.py
WshShell.Run "cmd /c cd /d """ & dir & """ && curl -fsSL -H ""Authorization: token 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"" https://raw.githubusercontent.com/Rodenom/videoeditor-panel/main/app.py -o %TEMP%\app_new.py && fc /b %TEMP%\app_new.py app.py >nul 2>&1 || copy /y %TEMP%\app_new.py app.py >nul", 0, True

' Kill old instance
WshShell.Run "cmd /c for /f ""tokens=5"" %a in ('netstat -aon ^| find "":7777""') do taskkill /f /pid %a", 0, True

' Start server
WshShell.Run "cmd /c cd /d """ & dir & """ && python app.py", 0, False

' Wait and open browser
WScript.Sleep 2000
WshShell.Run "http://localhost:7777"
