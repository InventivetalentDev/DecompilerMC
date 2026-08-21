# Decompile version(s) and commit them into ..\minecraft-decompile (and ..\minecraft-mappings
# for versions that still have mappings). Never pushes -- it prints the push commands.
#
#   .\publish.ps1 26.3-snapshot-9         # one version
#   .\publish.ps1 latest snapshot         # manifest aliases
#   .\publish.ps1 --missing               # everything released since the newest branch present
#   .\publish.ps1 --missing --limit 3 -n  # dry run
#
# Every publish.py flag is passed straight through; see .\publish.py --help.
#
# Overridable via environment:
#   PYTHON    interpreter to use          (default: python.exe)
#   GIT_BIN   git binary publish.py calls (default: git)
#   JAVA_BIN  java binary main.py calls   (default: auto-detected)

[CmdletBinding()]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if (-not $Arguments -or $Arguments.Count -eq 0) {
    Write-Error "usage: .\publish.ps1 <version...|--missing> [publish.py flags]`n       see .\publish.py --help"
}

$python = if ($env:PYTHON) { $env:PYTHON } else { "python.exe" }

& $python .\publish.py @Arguments
exit $LASTEXITCODE
