#!/usr/bin/env python3
"""Native frozen-stage baseline reproduction, PR594 pair rebuild and unsigned packaging.
Run ONLY in the pinned recovered cache image, with this directory at /trial.
No install, device access, forced loading, network, publication, or catalog edits.
"""
import gzip, hashlib, io, json, os, pathlib, re, shutil, struct, subprocess, tarfile
ROOT = pathlib.Path('/trial')
BASE = 'f1e136a24ceff4ba1817dfb71613842e764558ee'
CACHE = 'ghcr.io/armada-os/armada/buildcache/kernel@sha256:800dc72b1709e141e06eeb1887410a30db0bc26f7a785e084f6d4ac21e81ed6c'
PATCHES = [
 ('1021-wifi-ath12k-fix-single-pdev-frequency-ranges.patch', '96c1094f2403d73304adfc79d6eee6e38f1b055175b40d4e5982c04a2d53d25c'),
 ('1022-wifi-ath12k-split-WCN7860-scans-by-firmware-ranges.patch', '0227df4201f14c11f9ba2fb07e88572bc81ea7ac31c00d0f0979d634d070a251'),
 ('1023-wifi-ath12k-protect-TX-during-associated-range-scans.patch', '9f8cc31a135ff55fa4a1535dc77d16e5416dd8efd00a390743db76cb80667c71')]
MODULES = {'ath12k': 'drivers/net/wireless/ath/ath12k/ath12k.ko', 'ath12k_wifi7': 'drivers/net/wireless/ath/ath12k/wifi7/ath12k_wifi7.ko'}
VERMAGIC = '7.2.6 SMP preempt mod_unload aarch64'
def sha(path):
    h = hashlib.sha256()
    with pathlib.Path(path).open('rb') as stream:
        while block := stream.read(1024*1024): h.update(block)
    return h.hexdigest()
def check(value, message):
    if not value: raise RuntimeError(message)
def run(args, cwd=None, capture=False):
    print('+ ' + ' '.join(map(str, args)), flush=True)
    proc = subprocess.run(list(map(str, args)), cwd=cwd, check=True, text=True, stdout=subprocess.PIPE if capture else None)
    return proc.stdout.strip() if capture else None
def write_json(path, data): pathlib.Path(path).write_text(json.dumps(data, sort_keys=True, indent=2) + '\n')
def files(root): return {str(p.relative_to(root)): sha(p) for p in root.rglob('*') if p.is_file() and not p.is_symlink()}
def module_info(path):
    data = pathlib.Path(path).read_bytes()
    check(data[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<HH', data, 16) == (1, 183), 'not AArch64 ET_REL')
    def info(key):
        return run(['modinfo', '-F', key, path], capture=True)
    ids = re.findall(r'Build ID: ([0-9a-f]+)', run(['readelf', '-n', path], capture=True))
    check(len(ids) == 1 and re.fullmatch('[0-9a-f]{16,128}', ids[0]), 'build ID not unique')
    check(info('vermagic') == VERMAGIC, 'wrong vermagic')
    check(not info('srcversion'), 'unexpected srcversion')
    return {'sha256': sha(path), 'vermagic': VERMAGIC, 'srcversion': None, 'build_id': ids[0], 'depends': sorted(filter(None, info('depends').split(',')))}
def symvers(path):
    rows = {}
    for line in pathlib.Path(path).read_text().splitlines():
        fields = line.split()
        check(len(fields) >= 4, 'malformed symvers')
        crc, symbol, owner, export = fields[:4]
        check(symbol not in rows, 'duplicate symvers symbol')
        rows[symbol] = {'crc': crc, 'owner': owner, 'export': export, 'namespace': fields[4] if len(fields) > 4 else ''}
    return rows

def main():
    check(os.uname().machine == 'aarch64', 'native aarch64 required')
    check(run(['gcc', '--version'], capture=True).splitlines()[0] == 'gcc (GCC) 16.2.1 20260819 (Red Hat 16.2.1-2)', 'wrong compiler')
    check(run(['ld', '-v'], capture=True) == 'GNU ld version 2.46.1-1.fc44', 'wrong linker')
    check(run(['pahole', '--version'], capture=True) == 'v1.32', 'wrong pahole')
    check(sha('/work/out/armada-kernel-7.2.6.tar.zst') == '48654f760ba3a143d1cd7678274e25e758eb8ca6d613713582e5ce0f4bcc0747', 'cache stage not official donor producer')
    official = ROOT / 'official-source/packages/kernel'
    pristine = files(official)
    cached = {p:h for p,h in files(pathlib.Path('/work')).items() if not p.startswith('out/')}
    check(pristine == cached, 'cached /work recipe differs from pinned official source')
    series = [line.split('#')[0].strip() for line in (official / 'patches/series').read_text().splitlines()]
    series = [line for line in series if line]
    check(len(series) == 198 and all(name not in series for name, _ in PATCHES), 'not pristine 198-patch baseline')
    donor = ROOT / 'donor'
    check(sha(donor / 'official.config') == '3cae56750274cbd5b90a788335389dfbd38ad9fcb526505593ee878dc208a04f', 'wrong recovered config')
    work = ROOT / 'build/work'
    output = ROOT / 'results'
    work.mkdir(parents=True, exist_ok=False)
    output.mkdir(exist_ok=False)
    (output / 'proof').mkdir()
    source_tar = ROOT / 'inputs/linux-7.2.6.tar.xz'
    check(sha(source_tar) == '039aef84f2b0994aeda3f4fcfc3d02ec9d7a9bbb9020ea264c43f446c860f606', 'wrong source archive')
    shutil.copyfile(source_tar, work / source_tar.name)
    inventory = run(['rpm', '-qa', '--qf', '%{NAME}-%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n'], capture=True)
    (output / 'proof/rpm-inventory.txt').write_text('\n'.join(sorted(inventory.splitlines())) + '\n')
    toolhash = {}
    for command in ('gcc', 'ld', 'as', 'strip', 'objcopy', 'pahole', 'make', 'ccache'):
        path = pathlib.Path(shutil.which(command)).resolve()
        toolhash[str(path)] = sha(path)
    cc1 = run(['gcc', '-print-prog-name=cc1'], capture=True)
    toolhash[cc1] = sha(cc1)
    write_json(output / 'proof/toolchain-hashes.json', toolhash)
    os.environ.update(ARCH='arm64', KBUILD_BUILD_USER='armada', KBUILD_BUILD_HOST='builder', KBUILD_BUILD_VERSION='1', KBUILD_BUILD_TIMESTAMP='Tue Oct 13 18:55:56 UTC 2026', WORK_DIR=str(work), OUT_DIR=str(output / 'baseline-kernel'), CCACHE_DIR=str(ROOT / 'build/ccache'))
    os.environ.pop('FAST', None)
    # Direct script, deliberately NOT /work/build.sh: never DNF-update frozen stage.
    run(['bash', '/work/scripts/build-kernel.sh'], cwd='/work')
    src = work / 'linux-7.2.6'
    stage = work / 'staging-7.2.6/lib/modules/7.2.6'
    check((src / '.config').read_bytes() == (donor / 'official.config').read_bytes(), 'baseline full config differs')
    check(sha(src / 'arch/arm64/boot/Image') == sha(donor / 'lib/modules/7.2.6/vmlinuz'), 'baseline Image not reproduced')
    stock_modules = {str(p.relative_to(donor / 'lib/modules/7.2.6')): sha(p) for p in (donor / 'lib/modules/7.2.6').rglob('*.ko')}
    baseline_modules = {str(p.relative_to(stage)): sha(p) for p in stage.rglob('*.ko')}
    check(stock_modules == baseline_modules, 'baseline entire installed module set/hashes differ')
    check((src / 'Module.symvers').is_file() and (src / 'vmlinux').is_file(), 'missing generated ABI inputs')
    baseline_vmlinux = sha(src / 'vmlinux')
    run(['objcopy', '--dump-section', '.BTF=' + str(output / 'proof/rebuilt-base.btf'), src / 'vmlinux', output / 'proof/vmlinux-inspection.elf'])
    check(sha(output / 'proof/rebuilt-base.btf') == sha(donor / 'base.btf'), 'baseline BTF differs')
    (output / 'proof/vmlinux-inspection.elf').unlink()
    shutil.copyfile(src / 'Module.symvers', output / 'proof/baseline.Module.symvers')
    shutil.copyfile(src / '.config', output / 'proof/official.config')
    old_symbols = symvers(src / 'Module.symvers')
    # Build source-matched modern libbpf/bpftool without adding packages or touching kernel code.
    bpftool_out = ROOT / 'build/bpftool'
    bpftool_out.mkdir()
    run(['make', '-C', src / 'tools/bpf/bpftool', 'OUTPUT=' + str(bpftool_out) + '/', 'bootstrap', '-j' + str(os.cpu_count())])
    bpftool = bpftool_out / 'bootstrap/bpftool'
    check(bpftool.is_file(), 'bpftool bootstrap path missing')
    def btf_dump(path, label, base=True):
        args = [str(bpftool)] + (['-B', str(donor / 'base.btf')] if base else []) + ['btf', 'dump', 'file', str(path), 'format', 'raw']
        with gzip.GzipFile(filename=str(output / 'proof' / (label + '.btf.txt.gz')), mode='wb', mtime=0) as zipped:
            proc = subprocess.run(args, check=True, stdout=subprocess.PIPE)
            zipped.write(proc.stdout)
    btf_dump(donor / 'base.btf', 'official-base', base=False)
    for name, rel in MODULES.items(): btf_dump(donor / ('lib/modules/7.2.6/kernel/' + rel), 'stock-' + name)
    baseline_report = {
      'schema_version': 1, 'method': 'full-config-image-btf-all-stripped-module-byte-reproduction-v1',
      'source_commit': BASE, 'source_archive_sha256': sha(source_tar), 'recipe_files': pristine,
      'kernel_sha256': sha(src / 'arch/arm64/boot/Image'), 'config_sha256': sha(src / '.config'),
      'btf_vmlinux_sha256': sha(donor / 'base.btf'), 'module_symvers_sha256': sha(src / 'Module.symvers'),
      'vmlinux_sha256': baseline_vmlinux, 'module_count': len(stock_modules), 'installed_modules': stock_modules,
      'toolchain_cache': CACHE, 'toolchain_hashes': toolhash, 'rpm_inventory_sha256': sha(output / 'proof/rpm-inventory.txt'),
      'bpftool_sha256': sha(bpftool), 'modversions': False, 'crc_abi_evidence': 'not available, CONFIG_MODVERSIONS=n',
      'timestamp': os.environ['KBUILD_BUILD_TIMESTAMP'], 'hardware_tested': False,
      'checks': {'config_equal': True, 'Image_equal': True, 'BTF_equal': True, 'all_module_hashes_equal': True, 'stock_split_btf_parse': True}}
    abi_hash = hashlib.sha256(json.dumps(baseline_report, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    write_json(output / 'proof/baseline-proof.json', baseline_report)
    # Only now modify the isolated ath12k source files.
    patchlog = []
    for name, digest in PATCHES:
        path = ROOT / 'patch-source/packages/kernel/patches' / name
        check(sha(path) == digest, 'patch hash mismatch: ' + name)
        content = path.read_text()
        paths = re.findall(r'^\+\+\+ b/(.+)$', content, re.M) + re.findall(r'^--- a/(.+)$', content, re.M)
        check(paths and all(p.startswith('drivers/net/wireless/ath/ath12k/') for p in paths), 'patch escapes pair scope')
        expected = len(re.findall(r'^@@ ', content, re.M))
        check(expected > 0, 'patch has no hunks')
        with path.open() as stream:
            proc = subprocess.run(['patch', '-p1', '--batch', '--forward', '-F0', '--dry-run', '--verbose'], cwd=src, stdin=stream, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=True)
        check(len(re.findall(r'^Hunk #[0-9]+ succeeded', proc.stdout, re.M)) == expected, 'patch hunk count mismatch')
        check('fuzz' not in proc.stdout.lower() and 'offset' not in proc.stdout.lower(), 'patch offsets/fuzz not allowed')
        with path.open() as stream: subprocess.run(['patch', '-p1', '--batch', '--forward', '-F0', '--no-backup-if-mismatch'], cwd=src, stdin=stream, check=True)
        patchlog.append({'name': name, 'sha256': digest, 'hunks': expected, 'paths': sorted(set(paths)), 'preflight': proc.stdout})
    write_json(output / 'proof/patch-purity.json', patchlog)
    flags = ' '.join('-f' + kind + '-prefix-map=' + str(path) + '=' + mapped for path,mapped in ((src,'linux-7.2.6'),(work,'armada-kernel-build')) for kind in ('file','debug','macro'))
    os.environ.update(KCFLAGS=' ' + flags, HOSTCFLAGS=' ' + flags, KAFLAGS=' ' + flags)
    run(['make', '-C', src, '-j' + str(os.cpu_count()), 'CC=ccache gcc', 'M=drivers/net/wireless/ath/ath12k', 'modules'])
    check(sha(src / 'vmlinux') == baseline_vmlinux, 'baseline vmlinux was modified')
    check(sha(src / '.config') == baseline_report['config_sha256'], 'config was modified')
    new_symbols = symvers(src / 'drivers/net/wireless/ath/ath12k/Module.symvers')
    pair_prefix = 'drivers/net/wireless/ath/ath12k/'
    pair_symbols = {s:r for s,r in old_symbols.items() if r['owner'].startswith(pair_prefix)}
    # Kbuild may spell external owners absolute; compare owner basename plus all contract metadata.
    def contracts(rows): return {s:{**r, 'owner': pathlib.Path(r['owner']).name} for s,r in rows.items()}
    check(contracts(pair_symbols) == contracts(new_symbols), 'exported pair symbol contract changed')
    pairdir = output / 'pair'
    pairdir.mkdir()
    metadata, imports = {}, {}
    for name, rel in MODULES.items():
        dest = pairdir / (name + '.ko')
        shutil.copyfile(src / rel, dest)
        run(['strip', '--strip-debug', dest])
        metadata[name] = module_info(dest)
        expected_deps = ['cfg80211','mac80211'] + (['ath12k'] if name == 'ath12k_wifi7' else [])
        check(metadata[name]['depends'] == sorted(expected_deps), 'unexpected external dependencies')
        check(metadata[name]['sha256'] != stock_modules['kernel/' + rel], 'pair member is unmodified stock')
        btf_dump(dest, 'patched-' + name)
        undefined = run(['nm', '-u', dest], capture=True)
        symbols = sorted({line.split()[-1] for line in undefined.splitlines() if line.strip()})
        check(all(s in old_symbols or s in new_symbols for s in symbols), 'unresolved imports')
        imports[name] = {s: new_symbols.get(s, old_symbols.get(s)) for s in symbols}
    # Reports and an unpublished record are not put inside the strict two-file module archive.
    write_json(output / 'proof/pair-imports.json', imports)
    check(sha(src / 'vmlinux') == baseline_vmlinux, 'baseline vmlinux changed after validation')
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for name in sorted(MODULES):
            data = (pairdir / (name + '.ko')).read_bytes()
            info = tarfile.TarInfo(name + '.ko')
            info.size, info.mode, info.uid, info.gid, info.mtime = len(data), 0o644, 0, 0, 0
            archive.addfile(info, io.BytesIO(data))
    bundle = output / 'pr594-only-7.2.6-aarch64.tgz'
    with bundle.open('wb') as stream:
        with gzip.GzipFile(filename='', mode='wb', fileobj=stream, mtime=0) as zipped: zipped.write(payload.getvalue())
    target = json.loads((ROOT / 'target.json').read_text())
    stock = {name:module_info(donor / ('lib/modules/7.2.6/kernel/' + rel)) for name,rel in MODULES.items()}
    record = {'id': 'pr594-official-7-2-6-f1e136a-trial1', 'version': '0.1.0-trial1', 'patch_set': 'pr594-only', 'sha256': sha(bundle),
      'system': target, 'stock_modules': stock, 'modules': metadata, 'deployment': {'mode':'experimental-first-boot-v1'},
      'build': {'source_commit': BASE, 'config_sha256': baseline_report['config_sha256'], 'module_symvers_sha256': baseline_report['module_symvers_sha256'],
        'btf_vmlinux_sha256': baseline_report['btf_vmlinux_sha256'], 'toolchain': CACHE, 'pr594_patch_sha256': [h for _,h in PATCHES],
        'baseline_verified': True, 'baseline_abi_sha256': abi_hash, 'module_identity': 'sha256-gnu-build-id-v1', 'srcversion_all': False,
        'hardware_tested': False, 'proof_sha256': sha(output / 'proof/baseline-proof.json')}}
    write_json(output / 'package-record.unpublished.json', record)
    (output / 'SHA256SUMS').write_text(sha(bundle) + '  ' + bundle.name + '\n')
    print('OFFLINE PAIR BUILT; baseline reproduced. Unsigned/unpublished, not hardware-tested. No catalog URL assigned.', flush=True)
if __name__ == '__main__': main()
