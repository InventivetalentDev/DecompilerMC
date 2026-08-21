#!/usr/bin/env python3
import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
import time
from pathlib import Path
from shutil import which
from subprocess import CalledProcessError
from urllib.error import HTTPError, URLError

MANIFEST_LOCATION = f"https://piston-meta.mojang.com/mc/game/version_manifest_v2.json?{int(time.time())}"
CLIENT = "client"
SERVER = "server"

# WSL only has java.exe on PATH, Windows/Linux have java. Override with JAVA_BIN if needed.
JAVA = os.environ.get('JAVA_BIN') or ('java' if which('java') else (which('java.exe') and 'java.exe') or 'java')

# A Windows java launched from WSL cannot read /mnt/... paths, so translate what we hand it.
WINDOWS_JAVA_ON_WSL = sys.platform.startswith('linux') and JAVA.lower().endswith('.exe')


def jpath(path):
    """Render a path the way the java binary we are about to run expects to see it."""
    path = str(Path(path).resolve())
    if not WINDOWS_JAVA_ON_WSL:
        return path
    return subprocess.run(['wslpath', '-w', path],
                          stdout=subprocess.PIPE, text=True, check=True).stdout.strip()

VINEFLOWER = './lib/vineflower-1.12.0.jar'
CFR = './lib/cfr-0.2.2.jar'

# Flipped by --yes (and by publish.py); every prompt then silently takes its default.
NONINTERACTIVE = False


def prompt(message, default=""):
    """input() that returns `default` instead of blocking when running unattended."""
    if NONINTERACTIVE:
        print(f'{message}[auto: {default}]')
        return default
    return input(message) or default


def abortPrompt():
    if not NONINTERACTIVE:
        input("Aborting, press anything to exit")


def getMinecraftPath():
    if sys.platform.startswith('linux'):
        return Path("~/.minecraft")
    elif sys.platform.startswith('win'):
        return Path("~/AppData/Roaming/.minecraft")
    elif sys.platform.startswith('darwin'):
        return Path("~/Library/Application Support/minecraft")
    else:
        print("Cannot detect of version : %s. Please report to your closest sysadmin" % sys.platform)
        sys.exit()


mc_path = getMinecraftPath()


def checkjava():
    """Check for java and setup the proper directory if needed"""
    results = []
    if which(JAVA):
        results.append(JAVA)
    if sys.platform.startswith('win'):
        if not results:
            import winreg

            for flag in [winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY]:
                try:
                    k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'Software\JavaSoft\Java Development Kit', 0, winreg.KEY_READ | flag)
                    version, _ = winreg.QueryValueEx(k, 'CurrentVersion')
                    k.Close()
                    k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'Software\JavaSoft\Java Development Kit\%s' % version, 0, winreg.KEY_READ | flag)
                    path, _ = winreg.QueryValueEx(k, 'JavaHome')
                    k.Close()
                    path = os.path.join(str(path), 'bin')
                    subprocess.run(['"%s"' % os.path.join(path, 'java'), ' -version'], stdout=open(os.devnull, 'w'), stderr=subprocess.STDOUT, check=True)
                    results.append(path)
                except (CalledProcessError, OSError):
                    pass
        if not results:
            try:
                subprocess.run(['java', '-version'], stdout=open(os.devnull, 'w'), stderr=subprocess.STDOUT, check=True)
                results.append('')
            except (CalledProcessError, OSError):
                pass
        if not results and 'ProgramW6432' in os.environ:
            results.extend(filter(None, [which('java.exe', os.environ['ProgramW6432'])]))
        if not results and 'ProgramFiles' in os.environ:
            results.extend(filter(None, [which('java.exe', os.environ['ProgramFiles'])]))
        if not results and 'ProgramFiles(x86)' in os.environ:
            results.extend(filter(None, [which('java.exe', os.environ['ProgramFiles(x86)'])]))
    elif sys.platform.startswith('linux') or sys.platform.startswith('darwin'):
        if not results:
            try:
                subprocess.run(['java', '-version'], stdout=open(os.devnull, 'w'), stderr=subprocess.STDOUT, check=True)
                results.append('')
            except (CalledProcessError, OSError):
                pass
        if not results:
            results.extend(filter(None, [which('java', path='/usr/bin')]))
        if not results:
            results.extend(filter(None, [which('java', path='/usr/local/bin')]))
        if not results:
            results.extend(filter(None, [which('java', path='/opt')]))
    if not results:
        print('Java JDK is not installed ! Please install java JDK from http://java.oracle.com or OpenJDK')
        abortPrompt()
        sys.exit(1)

    print(results)


def getManifest(force=False):
    if not force and Path(f"versions/version_manifest.json").exists() and Path(f"versions/version_manifest.json").is_file():
        print("Manifest already existing, not downloading again, if you want to please accept safe removal at beginning")
        return
    downloadFile(MANIFEST_LOCATION, f"versions/version_manifest.json")


def downloadFile(url, filename):
    tmp = f'{filename}.{os.getpid()}.part'
    try:
        print(f'Downloading {filename}...')
        f = urllib.request.urlopen(url)
        with open(tmp, 'wb') as local_file:
            local_file.write(f.read())
        os.replace(tmp, filename)  # atomic, so a reader never sees a partial file
    except (HTTPError, URLError) as e:
        print(f'{"HTTP" if isinstance(e, HTTPError) else "URL"} Error downloading {url}')
        print(e)
        if os.path.exists(tmp):
            os.remove(tmp)
        raise

def getLatestVersion():
    """Read latest release/snapshot straight from the manifest, without touching disk."""
    print('Fetching the version manifest...')
    with urllib.request.urlopen(MANIFEST_LOCATION) as f:
        latest = json.load(f).get("latest") or {}
    return latest.get("snapshot"), latest.get("release")

def getVersionManifest(target_version, _retry=True):
    if Path(f"versions/{target_version}/version.json").exists() and Path(f"versions/{target_version}/version.json").is_file():
        print("Version manifest already existing, not downloading again, if you want to please accept safe removal at beginning")
        return
    path_to_json = Path(f'versions/version_manifest.json')
    if path_to_json.exists() and path_to_json.is_file():
        path_to_json = path_to_json.resolve()
        with open(path_to_json) as f:
            versions = json.load(f)["versions"]
            for version in versions:
                if version.get("id") and version.get("id") == target_version and version.get("url"):
                    downloadFile(version.get("url"), f"versions/{target_version}/version.json")
                    return
        # A cached manifest predating the requested version is the usual cause; refresh once.
        if _retry:
            print(f'{target_version} not in the cached manifest, refreshing it')
            getManifest(force=True)
            return getVersionManifest(target_version, _retry=False)
        print(f'ERROR: Unknown version: {target_version}')
        abortPrompt()
        sys.exit(1)
    else:
        print('ERROR: Missing manifest file: version.json')
        abortPrompt()
        sys.exit()


def getVersionJar(target_version, side):
    path_to_json = Path(f"versions/{target_version}/version.json")
    if Path(f"versions/{target_version}/{side}.jar").exists() and Path(f"versions/{target_version}/{side}.jar").is_file():
        print(f"versions/{target_version}/{side}.jar already existing, not downloading again")
        return
    if path_to_json.exists() and path_to_json.is_file():
        path_to_json = path_to_json.resolve()
        with open(path_to_json) as f:
            jsn = json.load(f)
            if jsn.get("downloads") and jsn.get("downloads").get(side) and jsn.get("downloads").get(side).get("url"):
                downloadFile(jsn.get("downloads").get(side).get("url"), f"versions/{target_version}/{side}.jar")
            else:
                print("Could not download jar, missing fields")
                abortPrompt()
                sys.exit()
    else:
        print('ERROR: Missing manifest file: version.json')
        abortPrompt()
        sys.exit()
    print("Done !")


def hasMappings(version, side):
    """Whether Mojang publishes ProGuard mappings for this version.

    They stopped as of 26.1-snapshot-1 (2025-12-16): from that version on the shipped
    jars are unobfuscated, so version.json has no {client,server}_mappings entry and
    there is nothing to remap.
    """
    path_to_json = Path(f'versions/{version}/version.json')
    if not (path_to_json.exists() and path_to_json.is_file()):
        print('ERROR: Missing manifest file: version.json')
        abortPrompt()
        sys.exit(1)
    with open(path_to_json) as f:
        downloads = json.load(f).get("downloads") or {}
    entry = downloads.get('client_mappings' if side == CLIENT else 'server_mappings')
    return bool(entry and entry.get("url"))


def getMappings(version, side):
    if Path(f'mappings/{version}/{side}.txt').exists() and Path(f'mappings/{version}/{side}.txt').is_file():
        print("Mappings already existing, not downloading again, if you want to please accept safe removal at beginning")
        return True
    path_to_json = Path(f'versions/{version}/version.json')
    if path_to_json.exists() and path_to_json.is_file():
        print(f'Found {version}.json')
        path_to_json = path_to_json.resolve()
        with open(path_to_json) as f:
            jfile = json.load(f)
            downloads = jfile.get('downloads') or {}
            if side not in (CLIENT, SERVER):
                print('ERROR, type not recognized')
                sys.exit(1)
            entry = downloads.get('client_mappings' if side == CLIENT else 'server_mappings')
            if not (entry and entry.get('url')):
                print(f'Error: Missing {side} mappings for {version} (this version ships unobfuscated)')
                return False
            url = entry['url']

            print(f'Downloading the mappings for {version}...')
            downloadFile(url, f'mappings/{version}/{side}.txt')
            return True
    else:
        print('ERROR: Missing manifest file: version.json')
        abortPrompt()
        sys.exit()


def extractServer(version, side):
    """Unwrap the bundler jar shipped since 21w39a. No-op if it is already unwrapped."""
    with zipfile.ZipFile(f'versions/{version}/{side}.jar') as z:
        inner = [n for n in z.namelist()
                 if n.startswith('META-INF/versions/') and n.endswith('.jar')]
    if not inner:
        print(f'versions/{version}/{side}.jar is not a bundler jar, nothing to extract')
        return
    inner_name = inner[0].split('/')[2]
    print(f'Extracting server jar from META-INF/versions/{inner_name}/server-{inner_name}.jar')
    shutil.rmtree(f'versions/{version}/server-inner', ignore_errors=True)
    with zipfile.ZipFile(f'versions/{version}/{side}.jar') as z:
        z.extract(f'META-INF/versions/{inner_name}/server-{inner_name}.jar', f'versions/{version}/{side}-inner')
    print(f'Moving server-inner/META-INF/versions/{inner_name}/server-{inner_name}.jar to versions/{version}/{side}.jar')
    os.remove(f'versions/{version}/{side}.jar')
    os.rename(f'versions/{version}/server-inner/META-INF/versions/{inner_name}/server-{inner_name}.jar', f'versions/{version}/{side}.jar')
    shutil.rmtree(f'versions/{version}/server-inner')


def remap(version, side):
    print(subprocess.run([JAVA, '--version'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True))
    print('=== Remapping jar using SpecialSource ====')
    t = time.time()
    path = Path(f'versions/{version}/{side}.jar')
    if not path.exists() or not path.is_file():
        path_temp = (mc_path / f'versions/{version}/{version}.jar').expanduser()
        if path_temp.exists() and path_temp.is_file():
            r = prompt("Error, defaulting to client.jar from your local Minecraft folder, continue? (y/n)", "y")
            if r != "y":
                sys.exit()
            path = path_temp
    mapp = Path(f'mappings/{version}/{side}.tsrg')
    specialsource = Path('./lib/SpecialSource-1.11.5-SNAPSHOT-shaded.jar')
    if path.exists() and mapp.exists() and specialsource.exists() and path.is_file() and mapp.is_file() and specialsource.is_file():
        path = path.resolve()
        mapp = mapp.resolve()
        specialsource = specialsource.resolve()
        subprocess.run([JAVA,
                        '-jar', jpath(specialsource),
                        '--in-jar', jpath(path),
                        '--out-jar', jpath(f'./src/{version}-{side}-temp.jar'),
                        '--srg-in', jpath(mapp),
                        "--kill-lvt"  # kill snowmen
                        ], check=True)
        print(f'- New -> {version}-{side}-temp.jar')
        t = time.time() - t
        print('Done in %.1fs' % t)
    else:
        print(f'ERROR: Missing files: {specialsource} or mappings/{version}/{side}.tsrg or versions/{version}/{side}.jar')
        abortPrompt()
        sys.exit(1)


def decompileFernFlower(decompiled_version, version, side, jar=None):
    print('=== Decompiling using Vineflower ===')
    t = time.time()
    path = Path(jar) if jar else Path(f'./src/{version}-{side}-temp.jar')
    fernflower = Path(VINEFLOWER)
    if path.exists() and fernflower.exists():
        path = path.resolve()
        fernflower = fernflower.resolve()
        print(f'Running {fernflower} on {path}')
        subprocess.run([JAVA,
                        '-Xmx8G',
                        '-Xms2G',
                        '-jar', jpath(fernflower),
                        '-hes=0',  # hide empty super invocation deactivated (might clutter but allow following)
                        '-hdc=0',  # hide empty default constructor deactivated (allow to track)
                        '-dgs=1',  # decompile generic signatures activated (make sure we can follow types)
                        '-ren=0',  # rename ambiguous activated
                        '-lit=1',  # output numeric literals
                        '-asc=1',  # encode non-ASCII characters in string and character
                        '-log=WARN',
                        jpath(path), jpath(f'./src/{decompiled_version}/{side}')
                        ], check=True)
        # print(f'- Removing -> {version}-{side}-temp.jar')
        # os.remove(f'./src/{version}-{side}-temp.jar')
        # print("Decompressing remapped jar to directory")
        # with zipfile.ZipFile(f'./src/{decompiled_version}/{side}/{version}-{side}-temp.jar') as z:
        #     z.extractall(path=f'./src/{decompiled_version}/{side}')
        t = time.time() - t
        print('Done in %.1fs' % t)
        #print(f'Remove Extra Jar file (file was decompressed in {decompiled_version}/{side})? (y/n): ')
        #response = input() or "n"
        #if response == 'y':
        #    print(f'- Removing -> {decompiled_version}/{side}/{version}-{side}-temp.jar')
        #    os.remove(f'./src/{decompiled_version}/{side}/{version}-{side}-temp.jar')
    else:
        print(f'ERROR: Missing files: {fernflower} or {path}')
        abortPrompt()
        sys.exit()


def decompileCFR(decompiled_version, version, side, jar=None):
    print('=== Decompiling using CFR (silent) ===')
    t = time.time()
    path = Path(jar) if jar else Path(f'./src/{version}-{side}-temp.jar')
    cfr = Path(CFR)
    if path.exists() and cfr.exists():
        path = path.resolve()
        cfr = cfr.resolve()
        subprocess.run([JAVA,
                        '-Xmx4G',
                        '-Xms1G',
                        '-jar', jpath(cfr),
                        jpath(path),
                        '--outputdir', jpath(f'./src/{decompiled_version}/{side}'),
                        '--caseinsensitivefs', 'true',
                        "--silent", "true"
                        ], check=True)
        if path.name.endswith('-temp.jar'):
            print(f'- Removing -> {path.name}')
            os.remove(path)
        summary = Path(f'./src/{decompiled_version}/{side}/summary.txt')
        if summary.is_file():
            print(f'- Removing -> summary.txt')
            summary.unlink()

        t = time.time() - t
        print('Done in %.1fs' % t)
    else:
        print(f'ERROR: Missing files: {cfr} or {path}')
        abortPrompt()
        sys.exit()


def removeBrackets(line, counter):
    while '[]' in line:  # get rid of the array brackets while counting them
        counter += 1
        line = line[:-2]
    return line, counter


def convertMappings(version, side):
    remap_primitives = {"int": "I", "double": "D", "boolean": "Z", "float": "F", "long": "J", "byte": "B", "short": "S", "char": "C", "void": "V"}
    remap_file_path = lambda path: "L" + "/".join(path.split(".")) + ";" if path not in remap_primitives else remap_primitives[path]
    with open(f'mappings/{version}/{side}.txt', 'r') as inputFile:
        file_name = {}
        for line in inputFile.readlines():
            if line.startswith('#'):  # comment at the top, could be stripped
                continue
            deobf_name, obf_name = line.split(' -> ')
            if not line.startswith('    '):
                obf_name = obf_name.split(":")[0]
                file_name[remap_file_path(deobf_name)] = obf_name  # save it to compare to put the Lb

    with open(f'mappings/{version}/{side}.txt', 'r') as inputFile, open(f'mappings/{version}/{side}.tsrg', 'w+') as outputFile:
        for line in inputFile.readlines():
            if line.startswith('#'):  # comment at the top, could be stripped
                continue
            deobf_name, obf_name = line.split(' -> ')
            if line.startswith('    '):
                obf_name = obf_name.rstrip()  # remove leftover right spaces
                deobf_name = deobf_name.lstrip()  # remove leftover left spaces
                method_type, method_name = deobf_name.split(" ")  # split the `<methodType> <methodName>`
                method_type = method_type.split(":")[-1]  # get rid of the line numbers at the beginning for functions eg: `14:32:void`-> `void`
                if "(" in method_name and ")" in method_name:  # detect a function function
                    variables = method_name.split('(')[-1].split(')')[0]  # get rid of the function name and parenthesis
                    function_name = method_name.split('(')[0]  # get the function name only
                    array_length_type = 0

                    method_type, array_length_type = removeBrackets(method_type, array_length_type)
                    method_type = remap_file_path(method_type)  # remap the dots to / and add the L ; or remap to a primitives character
                    method_type = "L" + file_name[method_type] + ";" if method_type in file_name else method_type  # get the obfuscated name of the class
                    if "." in method_type:  # if the class is already packaged then change the name that the obfuscated gave
                        method_type = "/".join(method_type.split("."))
                    for i in range(array_length_type):  # restore the array brackets upfront
                        if method_type[-1] == ";":
                            method_type = "[" + method_type[:-1] + ";"
                        else:
                            method_type = "[" + method_type

                    if variables != "":  # if there is variables
                        array_length_variables = [0] * len(variables)
                        variables = list(variables.split(","))  # split the variables
                        for i in range(len(variables)):  # remove the array brackets for each variable
                            variables[i], array_length_variables[i] = removeBrackets(variables[i], array_length_variables[i])
                        variables = [remap_file_path(variable) for variable in variables]  # remap the dots to / and add the L ; or remap to a primitives character
                        variables = ["L" + file_name[variable] + ";" if variable in file_name else variable for variable in variables]  # get the obfuscated name of the class
                        variables = ["/".join(variable.split(".")) if "." in variable else variable for variable in variables]  # if the class is already packaged then change the obfuscated name
                        for i in range(len(variables)):  # restore the array brackets upfront for each variable
                            for j in range(array_length_variables[i]):
                                if variables[i][-1] == ";":
                                    variables[i] = "[" + variables[i][:-1] + ";"
                                else:
                                    variables[i] = "[" + variables[i]
                        variables = "".join(variables)

                    outputFile.write(f'\t{obf_name} ({variables}){method_type} {function_name}\n')
                else:
                    outputFile.write(f'\t{obf_name} {method_name}\n')

            else:
                obf_name = obf_name.split(":")[0]
                outputFile.write(remap_file_path(obf_name)[1:-1] + " " + remap_file_path(deobf_name)[1:-1] + "\n")

    print("Done !")


def makePaths(version, side, removal_bool):
    path = Path(f'mappings/{version}')
    if not path.exists():
        path.mkdir(parents=True)
    else:
        if removal_bool:
            shutil.rmtree(path)
            path.mkdir(parents=True)
    path = Path(f'versions/{version}')
    if not path.exists():
        path.mkdir(parents=True)
    else:
        path = Path(f'versions/{version}/version.json')
        if path.is_file() and removal_bool:
            path.unlink()
    if Path("versions").exists():
        path = Path(f'versions/version_manifest.json')
        if path.is_file() and removal_bool:
            path.unlink()

    path = Path(f'versions/{version}/{side}.jar')
    if path.exists() and path.is_file() and removal_bool:
        aw = prompt(f"versions/{version}/{side}.jar already exists, wipe it (w) or ignore (i) ? ", "i")
        path = Path(f'versions/{version}')
        if aw == "w":
            shutil.rmtree(path)
            path.mkdir(parents=True)

    path = Path(f'src/{version}/{side}')
    if not path.exists():
        path.mkdir(parents=True)
    else:
        aw = prompt(f"/src/{version}/{side} already exists, wipe it (w), create a new folder (n) or kill the process (k) ? ", "w")
        if aw == "w":
            shutil.rmtree(Path(f"./src/{version}/{side}"))
        elif aw == "n":
            version = version + side + "_" + str(random.getrandbits(128))
        else:
            sys.exit()
        path = Path(f'src/{version}/{side}')
        path.mkdir(parents=True)
    return version


def main():
    snapshot, latest = getLatestVersion()
    if snapshot == None or latest == None:
        print("Error getting latest versions, please refresh cache")
        exit()

    parser = argparse.ArgumentParser(description="Decompile MC using mojang mappings")
    parser.add_argument("-r", "--removeold", help="Clean up old runs", action="store_true")
    parser.add_argument("-d", "--decompiler", choices=["cfr", "f"], help="Decompiler to use (CFR or Fernflower, defaults to Fernflower)", default="f")
    parser.add_argument("-m", "--manual", help="Manual mode, defaults to auto", action="store_true")
    parser.add_argument("-y", "--yes", help="Never prompt; take the default answer for every question (for unattended runs)", action="store_true")
    parser.add_argument("side", choices=["client", "server"], help="Side to decompile (Client or Server)")
    parser.add_argument("version", help="Version to decompile (or latest/snapshot)")

    args = parser.parse_args()
    print(args)

    global NONINTERACTIVE
    NONINTERACTIVE = args.yes

    checkjava()

    print("Decompiling using official mojang mappings (Default option are in uppercase, you can just enter)")
    removal_bool = 1 if args.removeold else 0
    decompiler = args.decompiler
    version = args.version
    if version in ["snapshot","snap","s"]:
        version=snapshot
    if version in ["latest","l"]:
        version=latest
    side = args.side
    side = CLIENT if side == "client" else SERVER
    decompiled_version = makePaths(version, side, removal_bool)
    getManifest()
    getVersionManifest(version)

    # Versions from 26.1-snapshot-1 on ship unobfuscated and publish no mappings,
    # so there is nothing to download or remap: decompile the shipped jar directly.
    mapped = hasMappings(version, side)
    print(f'{version} {side}: ' + ('obfuscated, will remap using official mappings'
                                   if mapped else 'ships unobfuscated, decompiling the jar as-is'))

    manual = args.manual
    if not manual:
        getVersionJar(version, side)

        # Extract server (>= 21w39a)
        if side == SERVER:
            extractServer(version, SERVER)

        jar = Path(f'versions/{version}/{side}.jar')
        if mapped:
            getMappings(version, side)
            convertMappings(version, side)
            remap(version, side)
            jar = Path(f'./src/{version}-{side}-temp.jar')

        if decompiler.lower() == "cfr":
            decompileCFR(decompiled_version, version, side, jar)
        else:
            decompileFernFlower(decompiled_version, version, side, jar)
        print("===FINISHED===")
        print(f"output is in /src/{decompiled_version}/{side}")
        if not NONINTERACTIVE:
            input("Press Enter key to exit")
        sys.exit(0)

    r = prompt(f'Get {version}-{side}.jar ? (y/n): ', "y")
    if r == "y":
        getVersionJar(version, side)
        if side == SERVER:
            extractServer(version, SERVER)

    jar = Path(f'versions/{version}/{side}.jar')
    if mapped:
        r = prompt('Download mappings? (y/n): ', "y")
        if r == 'y':
            getMappings(version, side)

        r = prompt('Remap mappings to tsrg? (y/n): ', "y")
        if r == 'y':
            convertMappings(version, side)

        r = prompt('Remap? (y/n): ', "y")
        if r == 'y':
            remap(version, side)
            jar = Path(f'./src/{version}-{side}-temp.jar')
    else:
        print('No mappings for this version, skipping the download/convert/remap steps')

    r = prompt('Decompile? (y/n): ', "y")
    if r == 'y':
        if decompiler.lower() == "cfr":
            decompileCFR(decompiled_version, version, side, jar)
        else:
            decompileFernFlower(decompiled_version, version, side, jar)

    print("===FINISHED===")
    print(f"output is in /src/{decompiled_version}/{side}")
    if not NONINTERACTIVE:
        input("Press Enter key to exit")


if __name__ == "__main__":
    main()
