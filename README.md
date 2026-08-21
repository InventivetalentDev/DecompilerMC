# DecompilerMC

---
**What is this for?**

This tool will help you convert mappings from mojang from their proguard format to the tsrg format that then can be used directly with specialsource which will then remap the client jar. Once that done it can be decompiled either with cfr (code only) or fernflower (assets and code).

Of course we provide all that toolchain directly so your output will be readable (and soon executable) code as you could get with MCP (ModCoderPack)

---
**Unobfuscated versions (26.1-snapshot-1 and later)**

As of `26.1-snapshot-1` (2025-12-16) Mojang ships the client and server jars unobfuscated and
no longer publishes ProGuard mappings: `version.json` has no `client_mappings` / `server_mappings`
entry at all. For those versions there is nothing to convert and nothing to remap, so the mapping
download, the tsrg conversion and the SpecialSource step are skipped and the shipped jar is handed
straight to the decompiler. Older versions still go through the full remap path exactly as before.

Detection is automatic per version and per side -- you do not need to pass a flag.

---
**Important Note**

You need an internet connection to download the mappings, you can ofc put them in the respective folder if you have them physically

We support Windows, MacOS and linux

You need a java runtime inside your path. Java 17+ is required by the bundled Vineflower.
Minecraft 26.x ships Java 25 class files (major version 69), so `lib/` carries Vineflower 1.12.0
(the current release) rather than the older 1.11.0 build; on a full 26.x client jar it fails to
decompile 1 method out of ~11k classes.

CFR decompilation is approximately 60s and Vineflower takes roughly 100s per side, please give it time

You can run it directly with python 3.5+ with `python3 main.py`

```
python3 main.py client 26.3-snapshot-9     # or: latest / snapshot
python3 main.py -y server 1.21.11          # -y never prompts, for unattended runs
```

If `java` is not the binary you want (for example under WSL, where only `java.exe` is on PATH),
point `JAVA_BIN` at the one to use:

```
JAVA_BIN=java.exe python3 main.py -y client latest
```

---
**Publishing to the decompile/mappings repos**

`publish.py` automates what used to be done by hand: decompile both sides, mirror the result into
`../minecraft-decompile`, branch, and commit. Each version is a commit on top of the previous one
with a branch of the same name, matching the existing history in those repos.

```
./publish.py 26.3-snapshot-9              # one version
./publish.py latest snapshot              # manifest aliases
./publish.py --missing                    # everything released since the newest branch present
./publish.py --missing --limit 3 -n       # -n / --dry-run: decompile and report, commit nothing
```

`publish.sh` and `publish.ps1` wrap it and pass every flag straight through:

```
./publish.sh --missing --limit 3 -n       # bash / WSL
.\publish.ps1 --missing --limit 3 -n      # PowerShell
```

The bash wrapper picks `python3` (falling back to `python.exe`) and, under WSL on a `/mnt`
path, exports `GIT_BIN=git.exe` for you. Set `PYTHON`, `GIT_BIN` or `JAVA_BIN` yourself to
override any of that.

It never pushes -- the push commands are printed at the end for you to run. Both repos must be
clean before it will touch them, and a failed version is rolled back to the branch it started on.

Under WSL, set `GIT_BIN=git.exe`: the Windows git is dramatically faster against a repo on `/mnt/...`
(a `git status` on `minecraft-decompile` takes ~1s instead of ~2 minutes); `publish.sh` does this
for you. `--skip-clean-check` skips that check entirely if you would rather not wait for it.

Note that the Linux git and git.exe read different gitconfigs and so can disagree on `user.email`.
To keep the chain consistent whichever one runs, commits reuse the author of the repo's newest
commit; pass `--author "Name <email>"` to choose a different one.

An interrupted run leaves a half-decompiled `src/<version>/<side>`. That is detected (via a
`src/<version>/.<side>.complete` marker) and redone rather than committed, so it is safe to
Ctrl-C a long `--missing` run and start it again.

For versions that still have mappings, `../minecraft-mappings` gets the same treatment
(`client.txt`, `client.tsrg`, `server.txt`, `server.tsrg`). For unobfuscated versions there are no
mappings, so that repo is left alone.

There is a common release here:  https://github.com/hube12/DecompilerMC/releases/tag/0.4 for all version

----

Build command (for executable):

```python
pip install pyinstaller
pyinstaller main.py --distpath build --onefile
```