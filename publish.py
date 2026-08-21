#!/usr/bin/env python3
"""Decompile a Minecraft version and commit it to the minecraft-decompile / minecraft-mappings repos.

This is the automation around main.py that used to be done by hand: run the decompiler for
both sides, mirror the result into the target repo, branch, and commit.

    ./publish.py 26.3-snapshot-9      # one version
    ./publish.py latest snapshot      # manifest aliases
    ./publish.py --missing            # every version released since the newest branch already present
    ./publish.py --missing --limit 3 --dry-run

Both repos are treated as a linear chain: each version is a commit on top of the previous one,
with a branch of the same name pointing at it. Nothing is ever pushed -- the push commands are
printed at the end for you to run.

Versions from 26.1-snapshot-1 (2025-12-16) on ship unobfuscated and publish no mappings at all,
so for those the mappings repo is left untouched.
"""
import argparse
import filecmp
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST_LOCATION = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
SIDES = ("client", "server")

# git on these repos is slow (tens of thousands of files, often on a mounted drive).
# Under WSL, git.exe against a /mnt/... repo is dramatically faster than the Linux git
# (~1s vs ~2min for a status on minecraft-decompile); point GIT_BIN at whichever is quicker.
GIT = os.environ.get('GIT_BIN') or 'git'
GIT_TIMEOUT = 3600


class Fail(Exception):
    pass


def log(msg):
    print(f'[publish] {msg}', flush=True)


# --------------------------------------------------------------------------- manifest

def fetchManifest(cache=HERE / 'versions' / 'version_manifest.json', max_age=300):
    """Return the parsed version manifest, refreshing the on-disk cache when it is stale."""
    cache.parent.mkdir(parents=True, exist_ok=True)
    if not cache.is_file() or time.time() - cache.stat().st_mtime > max_age:
        log('refreshing version manifest')
        with urllib.request.urlopen(f'{MANIFEST_LOCATION}?{int(time.time())}') as f:
            cache.write_bytes(f.read())
    return json.loads(cache.read_text())


def versionInfo(manifest, version):
    for v in manifest['versions']:
        if v['id'] == version:
            return v
    raise Fail(f'unknown version: {version}')


def resolveAlias(manifest, version):
    if version in ('latest', 'l', 'release'):
        return manifest['latest']['release']
    if version in ('snapshot', 'snap', 's'):
        return manifest['latest']['snapshot']
    return version


def hasMappings(manifest, version):
    """Whether Mojang still publishes ProGuard mappings for this version."""
    with urllib.request.urlopen(versionInfo(manifest, version)['url']) as f:
        downloads = json.load(f).get('downloads') or {}
    return all((downloads.get(f'{side}_mappings') or {}).get('url') for side in SIDES)


# --------------------------------------------------------------------------- git

def git(repo, *args, check=True, timeout=GIT_TIMEOUT):
    # encoding must be pinned: text=True would use the locale encoding (cp1252 on
    # Windows) while git always speaks UTF-8, which mangles non-ASCII author names.
    r = subprocess.run([GIT, *args], cwd=str(repo), capture_output=True,
                       encoding='utf-8', errors='replace', timeout=timeout)
    if check and r.returncode != 0:
        hint = ''
        if 'Filename too long' in r.stderr:
            # Windows MAX_PATH. The deepest Minecraft data path is ~145 chars, so this only
            # bites when the repo itself sits somewhere deep (a \\wsl.localhost\... share, say).
            hint = ('\nhint: Windows 260-char path limit. Either move the repo somewhere '
                    'shallower, or run: git config --global core.longpaths true')
        raise Fail(f'git {" ".join(args)} failed in {repo}:\n{r.stdout}{r.stderr}{hint}')
    return r.stdout.strip()


def repoIdentity(repo):
    """The author of the repo's newest commit.

    Worth pinning explicitly: the Linux git and git.exe read different gitconfigs, so the
    same repo picks up a different user.email depending on which binary runs. Reusing what
    the history already uses keeps the chain consistent either way.
    """
    name = git(repo, 'log', '-1', '--format=%an')
    email = git(repo, 'log', '-1', '--format=%ae')
    # Guard against feeding corruption forward: this value gets written into the next
    # commit, which the version after that reads back, so any mangling compounds.
    if '\ufffd' in name or '\ufffd' in email:
        raise Fail(f'{repo}: undecodable author in the last commit ({name!r} <{email!r}>). '
                   f'Pass --author "Name <email>" explicitly.')
    if len(name) > 100 or len(email) > 100:
        raise Fail(f'{repo}: implausible author in the last commit ({name[:60]!r}...). '
                   f'It looks corrupted; pass --author "Name <email>" explicitly.')
    return name, email


def branches(repo):
    return set(git(repo, 'for-each-ref', '--format=%(refname:short)', 'refs/heads').splitlines())


def requireCleanRepo(repo):
    log(f'checking {repo.name} is clean (this takes a while on a big repo)')
    dirty = git(repo, 'status', '--porcelain', '--untracked-files=normal')
    if dirty:
        raise Fail(f'{repo} has uncommitted changes, refusing to touch it:\n'
                   + '\n'.join(dirty.splitlines()[:20]))


def mirror(src: Path, dst: Path):
    """Make dst an exact copy of src, deleting anything that is no longer there.

    Consecutive snapshots differ in only a fraction of their files, so this copies just
    what actually changed rather than wiping and rewriting the whole tree.
    """
    if shutil.which('rsync'):
        dst.mkdir(parents=True, exist_ok=True)
        subprocess.run(['rsync', '-a', '--delete', f'{src}/', f'{dst}/'], check=True)
        return

    dst.mkdir(parents=True, exist_ok=True)
    wanted = set()
    copied = 0
    for root, dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        (dst / rel).mkdir(parents=True, exist_ok=True)
        wanted.add(rel)
        for name in files:
            target = dst / rel / name
            wanted.add(rel / name)
            source = Path(root) / name
            # shallow=False: mtime always differs on a fresh decompile, content usually doesn't
            if target.is_file() and filecmp.cmp(source, target, shallow=False):
                continue
            shutil.copy2(source, target)
            copied += 1

    removed = 0
    for root, dirs, files in os.walk(dst, topdown=False):
        rel = Path(root).relative_to(dst)
        for name in files:
            if rel / name not in wanted:
                (dst / rel / name).unlink()
                removed += 1
        if rel != Path('.') and rel not in wanted:
            try:
                (dst / rel).rmdir()
            except OSError:
                pass  # still holds ignored files (e.g. client/assets)
    log(f'  {copied} file(s) written, {removed} removed')


def commitVersion(repo, version, populate, dry_run, author=None):
    """Branch off the current HEAD, replace the tracked content, and commit."""
    existing = branches(repo)
    if version in existing:
        log(f'{repo.name}: branch {version} already exists, skipping')
        return False

    base = git(repo, 'rev-parse', '--abbrev-ref', 'HEAD')
    if base == 'HEAD':  # detached
        base = git(repo, 'rev-parse', 'HEAD')
    log(f'{repo.name}: branching {version} off {base}')
    if dry_run:
        log(f'{repo.name}: [dry-run] would populate, commit "{version}"')
        return True

    name, email = author or repoIdentity(repo)
    ident = ['-c', f'user.name={name}', '-c', f'user.email={email}']
    log(f'{repo.name}: committing as {name} <{email}>')

    git(repo, 'checkout', '-b', version)
    try:
        populate(repo)
        git(repo, 'add', '-A')
        if not git(repo, 'status', '--porcelain'):
            log(f'{repo.name}: no content change vs {base}, committing an empty commit to keep the chain')
            git(repo, *ident, 'commit', '--allow-empty', '-m', version)
        else:
            git(repo, *ident, 'commit', '-m', version)
    except Exception:
        # leave the repo where we found it rather than on a half-built branch
        log(f'{repo.name}: failed, rolling back to {base}')
        git(repo, 'reset', '--hard', check=False)
        git(repo, 'clean', '-fd', check=False)  # -d but not -x: never touches ignored assets
        git(repo, 'checkout', base, check=False)
        git(repo, 'branch', '-D', version, check=False)
        raise
    log(f'{repo.name}: committed {version} ({git(repo, "rev-parse", "--short", "HEAD")})')
    return True


# --------------------------------------------------------------------------- work

def decompile(version, side, decompiler, force):
    out = HERE / 'src' / version / side
    # Sits beside the output rather than inside it, so it never reaches the repo.
    # Without it an interrupted run leaves a half-decompiled tree that the next run
    # would happily reuse and commit.
    marker = HERE / 'src' / version / f'.{side}.complete'

    if marker.is_file() and out.is_dir() and not force:
        log(f'{version} {side}: src/{version}/{side} already complete, reusing it')
        return out
    if out.is_dir() and any(out.iterdir()):
        why = 'forced' if marker.is_file() else 'incomplete output from an earlier run'
        log(f'{version} {side}: discarding {why}')
    if out.exists():
        shutil.rmtree(out)

    log(f'{version} {side}: decompiling')
    t = time.time()
    r = subprocess.run([sys.executable, str(HERE / 'main.py'), '-y',
                        '-d', decompiler, side, version], cwd=HERE)
    if r.returncode != 0:
        raise Fail(f'main.py failed for {version} {side} (exit {r.returncode})')
    if not out.is_dir() or not any(out.iterdir()):
        raise Fail(f'main.py produced nothing in {out}')
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()
    log(f'{version} {side}: decompiled in {time.time() - t:.0f}s')
    return out


def publish(version, manifest, args, committed):
    log(f'=== {version} ===')
    mapped = hasMappings(manifest, version)
    log(f'{version}: {"obfuscated (mappings published)" if mapped else "unobfuscated (no mappings)"}')

    outputs = {side: decompile(version, side, args.decompiler, args.force_decompile)
               for side in SIDES}

    def populateDecompile(repo):
        for side, out in outputs.items():
            log(f'{repo.name}: mirroring {out} -> {repo / side}')
            mirror(out, repo / side)

    if commitVersion(args.decompile_repo, version, populateDecompile, args.dry_run, args.author):
        committed.setdefault(args.decompile_repo, []).append(version)

    if not mapped:
        log(f'{version}: no mappings, leaving {args.mappings_repo.name} untouched')
        return
    if not args.mappings_repo.is_dir():
        log(f'{version}: {args.mappings_repo} not found, skipping the mappings repo')
        return

    def populateMappings(repo):
        for side in SIDES:
            for ext in ('txt', 'tsrg'):
                src = HERE / 'mappings' / version / f'{side}.{ext}'
                if not src.is_file():
                    raise Fail(f'expected {src} to exist')
                log(f'{repo.name}: copying {src.name}')
                shutil.copy2(src, repo / f'{side}.{ext}')

    if commitVersion(args.mappings_repo, version, populateMappings, args.dry_run, args.author):
        committed.setdefault(args.mappings_repo, []).append(version)


def missingVersions(manifest, repo, since):
    """Versions released after the newest one already committed, oldest first."""
    have = branches(repo)
    times = {v['id']: v['releaseTime'] for v in manifest['versions']}
    if since:
        cutoff = times.get(since)
        if cutoff is None:
            raise Fail(f'unknown version: {since}')
    else:
        known = [times[b] for b in have if b in times]
        if not known:
            raise Fail(f'no branch in {repo} matches a manifest version, pass --since')
        cutoff = max(known)
    return [v['id'] for v in sorted(manifest['versions'], key=lambda v: v['releaseTime'])
            if v['releaseTime'] > cutoff and v['id'] not in have]


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('versions', nargs='*', help='versions to publish (or latest/snapshot)')
    p.add_argument('--missing', action='store_true',
                   help='publish every version released since the newest branch already present')
    p.add_argument('--since', metavar='VERSION',
                   help='with --missing, start after this version instead of the newest branch')
    p.add_argument('--limit', type=int, help='with --missing, stop after this many versions')
    p.add_argument('--decompile-repo', type=Path, default=HERE.parent / 'minecraft-decompile')
    p.add_argument('--mappings-repo', type=Path, default=HERE.parent / 'minecraft-mappings')
    p.add_argument('-d', '--decompiler', choices=['cfr', 'f'], default='f')
    p.add_argument('--force-decompile', action='store_true',
                   help='re-run the decompiler even if src/<version>/<side> is already populated')
    p.add_argument('--keep', action='store_true',
                   help='keep src/<version> and the downloaded jars after publishing')
    p.add_argument('--skip-clean-check', action='store_true',
                   help='skip the (slow) git status check that the repos have no uncommitted changes')
    p.add_argument('--author', metavar='"Name <email>"',
                   help='commit as this identity (default: whoever authored the repo\'s newest commit)')
    p.add_argument('-n', '--dry-run', action='store_true',
                   help='decompile and report, but make no commits')
    args = p.parse_args()

    args.decompile_repo = args.decompile_repo.resolve()
    args.mappings_repo = args.mappings_repo.resolve()

    if args.author:
        if '<' not in args.author or not args.author.rstrip().endswith('>'):
            raise Fail(f'--author must look like "Name <email>", got: {args.author}')
        name, _, email = args.author.rstrip().rstrip('>').partition('<')
        args.author = (name.strip(), email.strip())

    if not args.missing and not args.versions:
        p.error('give at least one version, or --missing')

    manifest = fetchManifest()

    if not args.decompile_repo.is_dir():
        raise Fail(f'{args.decompile_repo} is not a directory')

    versions = [resolveAlias(manifest, v) for v in args.versions]
    if args.missing:
        found = missingVersions(manifest, args.decompile_repo, args.since)
        log(f'{len(found)} version(s) missing from {args.decompile_repo.name}')
        if args.limit:
            found = found[:args.limit]
        versions += [v for v in found if v not in versions]

    for v in versions:
        versionInfo(manifest, v)  # fail fast on typos before doing any work
    if not versions:
        log('nothing to do')
        return
    log(f'publishing {len(versions)} version(s): {", ".join(versions)}')

    if not args.dry_run and not args.skip_clean_check:
        requireCleanRepo(args.decompile_repo)
        if args.mappings_repo.is_dir():
            requireCleanRepo(args.mappings_repo)

    committed = {}
    for v in versions:
        publish(v, manifest, args, committed)
        if not args.keep and not args.dry_run:
            # the decompiled tree is in the repo now and the jars are ~100MB a side
            shutil.rmtree(HERE / 'src' / v, ignore_errors=True)
            shutil.rmtree(HERE / 'versions' / v, ignore_errors=True)
            for leftover in HERE.glob(f'src/{v}-*-temp.jar'):
                leftover.unlink()

    log('=== done ===')
    if args.dry_run:
        return
    if not committed:
        log('no new commits')
        return
    log('nothing was pushed. To publish:')
    for repo, vs in committed.items():
        print(f'    (cd {repo} && git push origin {" ".join(vs)})')


if __name__ == '__main__':
    try:
        main()
    except Fail as e:
        print(f'[publish] ERROR: {e}', file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
