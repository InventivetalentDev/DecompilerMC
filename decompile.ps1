$version = $args[0]
Start-Sleep -s 1
Start-Process Powershell.exe -ArgumentList "python.exe .\main.py client $version"
Start-Sleep -s 1 # Breaks for some reason if you launch these too quickly
Start-Process Powershell.exe -ArgumentList "python.exe .\main.py server $version"
Start-Sleep -s 1