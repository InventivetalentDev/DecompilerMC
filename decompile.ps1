# Decompile both sides of a version into .\src\<version>\{client,server}.
# This only decompiles -- use .\publish.py to also commit into the mc repos.
#
#   .\decompile.ps1 26.3-snapshot-9
param([Parameter(Mandatory=$true)][string]$version)

$python = if ($env:PYTHON) { $env:PYTHON } else { "python.exe" }

Remove-Item .\versions\version_manifest.json -ErrorAction SilentlyContinue
Remove-Item .\src\$version -Recurse -ErrorAction SilentlyContinue
Remove-Item .\versions\$version -Recurse -ErrorAction SilentlyContinue
Remove-Item .\mappings\$version -Recurse -ErrorAction SilentlyContinue

# -y so neither run blocks on a prompt
Start-Process $python -ArgumentList ".\main.py -y client $version"
Start-Sleep -s 1 # Breaks for some reason if you launch these too quickly
Start-Process $python -ArgumentList ".\main.py -y server $version"
