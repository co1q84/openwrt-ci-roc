#!/usr/bin/env python3
"""Prepare the locked x86 build and reject silent feature/layout loss."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import struct
import tarfile
from datetime import datetime, timezone

REPO = Path(__file__).resolve().parents[1]


def run(*args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True)


def config_values(path):
    values = {}
    for line in path.read_text().splitlines():
        if line.startswith('CONFIG_') and '=' in line:
            key, value = line.split('=', 1)
            values[key] = value
        elif line.startswith('# CONFIG_') and line.endswith(' is not set'):
            values[line[2:-11]] = 'n'
    return values


def required_config(repo=REPO):
    values = {}
    for name in ('General.config', 'x86-packages.config', 'x86-64.config'):
        values.update(config_values(repo / 'configs' / name))
    # NSS is specific to the other target. No common config file is changed.
    values.pop('CONFIG_PACKAGE_sqm-scripts-nss', None)
    # Current Argon includes the former standalone configuration application.
    values.pop('CONFIG_PACKAGE_luci-app-argon-config', None)
    return values


def check_config(path, required):
    actual = config_values(path)
    errors = [f'{key}: expected {value}, got {actual.get(key, "missing")}'
              for key, value in required.items()
              if actual.get(key, 'n') != value]
    if errors:
        raise ValueError('Resolved configuration lost required settings:\n' + '\n'.join(errors))


def validate_lock(lock):
    for entry in [lock['source'], *lock['feeds'].values(), *lock['extras'].values()]:
        if not re.fullmatch('[0-9a-f]{40}', entry['commit']):
            raise ValueError('Every source commit must be a full immutable Git SHA')
        if not entry['url'].startswith('https://github.com/') or not entry['url'].endswith('.git'):
            raise ValueError('Source URL must be a public GitHub HTTPS repository')


def resolve_ref(url, ref):
    result = subprocess.check_output(['git', 'ls-remote', url, ref], text=True)
    rows = result.splitlines()
    if len(rows) != 1 or not re.fullmatch('[0-9a-f]{40}', rows[0].split()[0]):
        raise ValueError(f'Cannot resolve exactly one commit for {url} {ref}')
    return rows[0].split()[0]


def resolve_sources(policy):
    lock = json.loads(json.dumps(policy))
    entries = [lock['source'], *lock['feeds'].values(), *lock['extras'].values()]
    def resolve(entry):
        entry['commit'] = resolve_ref(entry['url'], entry['ref'])
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(resolve, entries))
    validate_lock(lock)
    return lock


def checkout(entry, destination):
    if not (destination / '.git').is_dir():
        destination.mkdir(parents=True, exist_ok=True)
        run('git', 'init', str(destination))
        run('git', '-C', str(destination), 'remote', 'add', 'origin', entry['url'])
    remote = subprocess.check_output(['git', '-C', str(destination), 'remote', 'get-url', 'origin'], text=True).strip()
    if remote != entry['url']:
        raise ValueError(f'Unexpected repository at {destination}')
    run('git', '-C', str(destination), 'fetch', '--depth=1', 'origin', entry['commit'])
    run('git', '-C', str(destination), 'checkout', '--detach', entry['commit'])
    actual = subprocess.check_output(['git', '-C', str(destination), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != entry['commit']:
        raise ValueError(f'Checkout mismatch: {destination}')


def install_overlay(source, repo):
    config = source / 'package/base-files/files/bin/config_generate'
    text = config.read_text().replace('192.168.1.1', '192.168.100.1')
    # config_generate is only used for absent config, never restored config.
    text = re.sub(r"hostname='[^']*'", "hostname='OpenWrt'", text)
    config.write_text(text)
    luci_config = source / 'feeds/luci/modules/luci-base/root/etc/config/luci'
    if luci_config.exists():
        luci_config.write_text(luci_config.read_text().replace('/luci-static/bootstrap', '/luci-static/argon'))
    # Register themes without overwriting the user's restored theme selection.
    for parent in (source / 'feeds/luci/themes', source / 'package/roc'):
        for script in parent.glob('**/root/etc/uci-defaults/30_luci-theme-*'):
            lines = script.read_text().splitlines(keepends=True)
            script.write_text(''.join(line for line in lines if 'set luci.main.mediaurlbase=' not in line))
    overlay = repo / 'files/x86'
    if overlay.exists():
        shutil.copytree(overlay, source / 'files', dirs_exist_ok=True, symlinks=True)
    core = source / 'files/etc/openclash/core/clash_meta'
    core.parent.mkdir(parents=True, exist_ok=True)
    if core.is_symlink() or core.exists():
        core.unlink()
    core.symlink_to('/usr/bin/mihomo')


def prepare(source, repo):
    lock_path = repo / 'configs/x86-sources.json'
    # Resolve fresh heads on EVERY run, then freeze only this run's inputs.
    lock = resolve_sources(json.loads(lock_path.read_text()))
    checkout(lock['source'], source)
    for name, entry in lock['feeds'].items():
        checkout(entry, source / 'feeds' / name)
    # update -i only generates indices. It cannot advance the checked-out commits.
    (source / 'feeds.conf').write_text(''.join(
        f'src-git {name} {e["url"]}^{e["commit"]}\n' for name, e in lock['feeds'].items()))
    for name, entry in lock['extras'].items():
        checkout(entry, source / 'package/roc' / name)
    # Override only packages whose explicitly locked upstream replaces a feed copy.
    for relative in ('feeds/luci/applications/luci-app-openclash',
                     'feeds/luci/applications/luci-app-tailscale-community'):
        path = source / relative
        if path.exists():
            shutil.rmtree(path)
    run('./scripts/feeds', 'update', '-i', cwd=source)
    for name in lock['feeds']:
        index = source / 'feeds' / f'{name}.index'
        if not index.exists() or index.stat().st_size == 0:
            raise ValueError(f'Feed index generation failed: {name}')
    run('./scripts/feeds', 'install', '-a', cwd=source)
    install_overlay(source, repo)
    requested = required_config(repo)
    (source / '.config').write_text(''.join(f'{k}={v}\n' for k, v in requested.items()))
    (source / 'sources.lock.json').write_text(json.dumps(lock, indent=2) + '\n')


def image_partitions(image):
    with gzip.open(image, 'rb') as stream:
        data = stream.read(256 * 1024)
    if len(data) < 1024 or data[510:512] != b'\x55\xaa' or data[512:520] != b'EFI PART':
        raise ValueError('Expected an EFI GPT image')
    table_lba = struct.unpack_from('<Q', data, 584)[0]
    count, size = struct.unpack_from('<II', data, 592)
    if count > 128 or size != 128 or table_lba * 512 + count * size > len(data):
        raise ValueError('Unsupported EFI GPT partition table')
    parts = []
    for index in range(count):
        offset = table_lba * 512 + index * size
        if not any(data[offset:offset+16]):
            continue
        # ptgen's final BIOS-boot entry is reserved bootloader space, not a filesystem.
        if data[offset:offset+16].hex() == '4861682149646f6e744e656564454649':
            continue
        start, end = struct.unpack_from('<QQ', data, offset + 32)
        parts.append([index + 1, start, end - start + 1])
    if len(parts) != 2 or [p[0] for p in parts] != [1, 2] or [p[2] for p in parts] != [131072, 1966080]:
        raise ValueError('Expected boot 64 MiB and root 960 MiB, no extra filesystem partitions')
    return parts


def check_manifest(path, required):
    versions = {}
    for line in path.read_text().splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[1] == '-':
            versions[fields[0]] = fields[2]
        elif len(fields) == 2:
            versions[fields[0]] = fields[1]
    missing = sorted(key.removeprefix('CONFIG_PACKAGE_') for key, value in required.items()
                     if key.startswith('CONFIG_PACKAGE_') and value == 'y'
                     and key.removeprefix('CONFIG_PACKAGE_') not in versions)
    if missing:
        raise ValueError('Image manifest is missing required packages: ' + ', '.join(missing))
    return versions


def asset_info(path):
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'name': path.name, 'size': path.stat().st_size, 'sha256': digest}


def write_checksums(output):
    (output / 'sha256sums').write_text(''.join(
        f'{asset_info(p)["sha256"]}  {p.name}\n' for p in sorted(output.iterdir())
        if p.is_file() and p.name != 'sha256sums'))


def release(source, output, repo, tag):
    if not re.fullmatch(r'x86-64-[0-9]+-[0-9]+', tag):
        raise ValueError('Release requires an immutable x86-64-RUN_ID-ATTEMPT tag')
    required = required_config(repo)
    check_config(source / '.config', required)
    target = source / 'bin/targets/x86/64'
    images = list(target.glob('*-generic-squashfs-combined-efi.img.gz'))
    manifests = list(target.glob('*-generic.manifest'))
    if len(images) != 1 or len(manifests) != 1:
        raise ValueError('Expected exactly one squashfs EFI image and package manifest')
    partitions = image_partitions(images[0])
    versions = check_manifest(manifests[0], required)
    output.mkdir(parents=True, exist_ok=False)
    for path in [images[0], manifests[0], *target.glob('*.buildinfo'), *target.glob('profiles.json')]:
        shutil.copy2(path, output / path.name)
    shutil.copy2(source / '.config', output / 'x86-64.config')
    shutil.copy2(source / 'sources.lock.json', output / 'sources.lock.json')
    shutil.copy2(repo / 'files/x86/usr/sbin/roc-update', output / 'roc-update')
    if (target / 'sha256sums').exists():
        shutil.copy2(target / 'sha256sums', output / 'upstream-sha256sums')
    # Keep build-matched APKs for offline recovery, never device configuration.
    with tarfile.open(output / 'x86-64-packages.tar.gz', 'w:gz') as archive:
        for parent, prefix in [(source / 'bin/packages', 'feeds'), (target / 'packages', 'target')]:
            for path in sorted(parent.rglob('*.apk')):
                archive.add(path, arcname=str(Path(prefix) / path.relative_to(parent)))
    image = asset_info(output / images[0].name)
    image.update({'partitions': partitions, 'filesystem': 'squashfs', 'boot': 'efi'})
    metadata = {'schema': 1, 'repository': 'co1q84/openwrt-ci-roc', 'tag': tag,
                'built_at': datetime.now(timezone.utc).isoformat(), 'target': 'x86/64',
                'device': 'J4125-4L', 'kernel': versions.get('kernel'),
                'image': image, 'manifest': asset_info(output / manifests[0].name),
                'packages': versions,
                'builder_commit': subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()}
    (output / 'release.json').write_text(json.dumps(metadata, indent=2) + '\n')
    write_checksums(output)
    print(f'Verified release: {tag}, kernel {metadata["kernel"]}, {len(versions)} packages')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'check-config', 'release'])
    parser.add_argument('source', type=Path)
    parser.add_argument('--repo', type=Path, default=REPO)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--tag')
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args.source.resolve(), args.repo.resolve())
    elif args.command == 'check-config':
        check_config(args.source / '.config', required_config(args.repo))
        print('Required x86 configuration verified')
    else:
        if not args.output or not args.tag:
            parser.error('release requires --output and --tag')
        release(args.source, args.output, args.repo, args.tag)


if __name__ == '__main__':
    main()
