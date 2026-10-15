#!/usr/bin/env python3
"""UNVERIFIED ABI experiment: prepare headers/tools and build only the PR594 pair.
Never build Image/all modules; never load/install/force modules. No network here.
The thin vmlinux contains ONLY recovered official BTF, NOT generated kernel code.
Synthetic zero-CRC symvers are explicitly NOT baseline ABI evidence.
"""
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tarfile

spec = importlib.util.spec_from_file_location('original_helpers', '/trial/build-native.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
ROOT, sha, check, run, write_json = base.ROOT, base.sha, base.check, base.run, base.write_json
PAIR = 'drivers/net/wireless/ath/ath12k'
SOURCE_SHA = '039aef84f2b0994aeda3f4fcfc3d02ec9d7a9bbb9020ea264c43f446c860f606'
CONFIG_SHA = '3cae56750274cbd5b90a788335389dfbd38ad9fcb526505593ee878dc208a04f'
BTF_SHA = '81399c2085e836a86095ce269a0df28e7d1c1ff6cc362806276e2f28672a2bd9'


def elf_symbols(path):
    """Read retained stock ELF symbol/string sections; never execute a module."""
    data = path.read_bytes()
    check(data[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<HH', data, 16) == (1, 183), 'stock not AArch64 ET_REL')
    offset = struct.unpack_from('<Q', data, 40)[0]
    size, count = struct.unpack_from('<HH', data, 58)
    check(size == 64 and count > 0 and offset + size * count <= len(data), 'ELF section bounds')
    sections = [struct.unpack_from('<IIQQQQIIQQ', data, offset + i * size) for i in range(count)]
    def body(index):
        check(0 <= index < count, 'bad ELF section index')
        section = sections[index]
        start, length = section[4:6]
        check(start + length <= len(data), 'ELF section bytes out of bounds')
        return data[start:start + length]
    def string(blob, start):
        check(start < len(blob), 'ELF string out of bounds')
        end = blob.find(b'\x00', start)
        check(end >= start, 'ELF unterminated string')
        return blob[start:end].decode('ascii')
    result = {}
    for index, section in enumerate(sections):
        if section[1] != 2:
            continue
        symbols, strings = body(index), body(section[6])
        check(section[9] == 24 and len(symbols) % 24 == 0, 'ELF symbol table bounds')
        for n in range(0, len(symbols), 24):
            name, info, other, shndx, value, length = struct.unpack_from('<IBBHQQ', symbols, n)
            label = string(strings, name)
            if label:
                result[label] = (shndx, value)
    def symbol_string(label):
        check(label in result, 'missing stock namespace label ' + label)
        index, value = result[label]
        return string(body(index), value)
    exports = {}
    for label, (index, value) in result.items():
        if label.startswith('__ksymtab_'):
            symbol = label[len('__ksymtab_'):]
            namespace = symbol_string('__kstrtabns_' + symbol)
            flags = 0
            if '__flags_' + symbol in result:
                flag_index, flag_value = result['__flags_' + symbol]
                flags = body(flag_index)[flag_value]
            check(flags in (0, 1), 'unknown stock export flags')
            exports[symbol] = {'owner': str(path), 'namespace': namespace,
                               'export': 'EXPORT_SYMBOL_GPL' if flags & 1 else 'EXPORT_SYMBOL'}
    undefined = {label for label, (index, _) in result.items() if index == 0}
    return exports, undefined


def apply_patch(src, path, exact):
    content = path.read_text()
    expected = len(re.findall(r'^@@ ', content, re.M))
    check(expected > 0, 'empty patch ' + path.name)
    with path.open() as stream:
        proc = subprocess.run(['patch', '-p1', '--batch', '--forward', '-F0', '--dry-run', '--verbose'],
                              cwd=src, stdin=stream, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    print(proc.stdout, flush=True)
    check(proc.returncode == 0 and len(re.findall(r'^Hunk #[0-9]+ succeeded', proc.stdout, re.M)) == expected,
          'incomplete patch ' + path.name)
    check('fuzz' not in proc.stdout.lower() and (not exact or 'offset' not in proc.stdout.lower()), 'patch fuzz/offset')
    with path.open() as stream:
        subprocess.run(['patch', '-p1', '--batch', '--forward', '-F0', '--no-backup-if-mismatch', '--quiet'],
                       cwd=src, stdin=stream, check=True)
    return {'name': path.name, 'sha256': sha(path), 'hunks': expected, 'preflight': proc.stdout}


def main():
    check(os.uname().machine == 'aarch64', 'native aarch64 required')
    check(run(['gcc', '--version'], capture=True).splitlines()[0] == 'gcc (GCC) 16.2.1 20260819 (Red Hat 16.2.1-2)', 'compiler mismatch')
    check(run(['ld', '-v'], capture=True) == 'GNU ld version 2.46.1-1.fc44', 'linker mismatch')
    check(run(['pahole', '--version'], capture=True) == 'v1.32', 'pahole mismatch')
    check(sha('/work/out/armada-kernel-7.2.6.tar.zst') == '48654f760ba3a143d1cd7678274e25e758eb8ca6d613713582e5ce0f4bcc0747', 'cache donor mismatch')
    official = ROOT / 'official-source/packages/kernel'
    check(base.files(official) == {p: h for p, h in base.files(Path('/work')).items() if not p.startswith('out/')}, 'recipe mismatch')
    donor = ROOT / 'donor'
    check(sha(donor / 'official.config') == CONFIG_SHA and sha(donor / 'base.btf') == BTF_SHA, 'config/BTF mismatch')
    work, output = ROOT / 'build/modules-only-work', ROOT / 'results'
    work.mkdir(parents=True, exist_ok=False)
    output.mkdir(exist_ok=False)
    proof = output / 'proof'
    proof.mkdir()
    source = ROOT / 'inputs/linux-7.2.6.tar.xz'
    check(sha(source) == SOURCE_SHA, 'source archive mismatch')
    with tarfile.open(source, 'r:xz') as archive:
        archive.extractall(work, filter='data')
    src = work / 'linux-7.2.6'
    check(src.is_dir(), 'source root absent')
    series = [line.split('#')[0].strip() for line in (official / 'patches/series').read_text().splitlines()]
    series = [line for line in series if line]
    check(len(series) == 198 and all(name not in series for name, _ in base.PATCHES), 'not untouched official series')
    baseline_patches = [apply_patch(src, official / 'patches' / name, False) for name in series]
    write_json(proof / 'official-patches.json', baseline_patches)
    changes = []
    for name, digest in base.PATCHES:
        path = ROOT / 'patch-source/packages/kernel/patches' / name
        check(sha(path) == digest, 'custom patch digest mismatch')
        paths = re.findall(r'^\+\+\+ b/(.+)$', path.read_text(), re.M) + re.findall(r'^--- a/(.+)$', path.read_text(), re.M)
        check(paths and all(p.startswith(PAIR + '/') for p in paths), 'custom patch escapes ath12k')
        changes.append(apply_patch(src, path, True))
    write_json(proof / 'patch-purity.json', changes)
    shutil.copyfile(donor / 'official.config', src / '.config')
    flags = ' '.join('-f' + kind + '-prefix-map=' + str(path) + '=' + mapped
                     for path, mapped in ((src, 'linux-7.2.6'), (work, 'armada-kernel-build'))
                     for kind in ('file', 'debug', 'macro'))
    os.environ.update(ARCH='arm64', KBUILD_BUILD_USER='armada', KBUILD_BUILD_HOST='builder',
                      KBUILD_BUILD_VERSION='1', KBUILD_BUILD_TIMESTAMP='Tue Oct 13 18:55:56 UTC 2026',
                      KCFLAGS=' ' + flags, HOSTCFLAGS=' ' + flags, KAFLAGS=' ' + flags)
    run(['make', '-C', src, 'olddefconfig'])
    check(sha(src / '.config') == CONFIG_SHA, 'config changed by olddefconfig')
    config = (src / '.config').read_text()
    check('CONFIG_MODVERSIONS=y' not in config and 'CONFIG_DEBUG_INFO_BTF_MODULES=y' in config, 'unsupported module config')
    run(['make', '-C', src, '-j' + str(os.cpu_count()), 'modules_prepare'])
    check(run(['make', '-s', '-C', src, 'kernelrelease'], capture=True) == '7.2.6', 'release mismatch')
    # Thin ELF is an explicitly labeled BTF container, never kernel executable ABI proof.
    run(['objcopy', '-I', 'binary', '-O', 'elf64-littleaarch64', '-B', 'aarch64',
         '--rename-section', '.data=.BTF,alloc,load,readonly,data,contents', donor / 'base.btf', src / 'vmlinux'])
    thin_sha = sha(src / 'vmlinux')
    (proof / 'thin-vmlinux.WARNING.txt').write_text('ONLY official raw BTF wrapped as ELF; NO kernel code, symbol addresses, layout reproduction or ABI verification.\n')
    shared, stock_imports, pair_exports, stock_records = {}, set(), {}, {}
    for name, rel in base.MODULES.items():
        path = donor / ('lib/modules/7.2.6/kernel/' + rel)
        exports, undefined = elf_symbols(path)
        pair_exports.update(exports)
        stock_imports.update(undefined)
        stock_records[name] = base.module_info(path)
    for name in ('cfg80211', 'mac80211', 'rfkill', 'libarc4'):
        matches = list((donor / 'lib/modules/7.2.6/kernel').rglob(name + '.ko'))
        check(len(matches) == 1, 'shared dependency missing/ambiguous ' + name)
        exports, _ = elf_symbols(matches[0])
        check(exports, 'no real shared exports ' + name)
        owner = str(matches[0].relative_to(donor / 'lib/modules/7.2.6/kernel')).removesuffix('.ko')
        for symbol, record in exports.items():
            check(symbol not in shared, 'duplicate shared export')
            shared[symbol] = dict(record, owner=owner)
    inferred = sorted(stock_imports - set(pair_exports) - set(shared))
    synthetic = {**{s: {'owner': 'vmlinux', 'namespace': '', 'export': 'EXPORT_SYMBOL'} for s in inferred}, **shared}
    text = ''.join('0x00000000\t%s\t%s\t%s\t%s\n' % (s, r['owner'], r['export'], r['namespace']) for s, r in sorted(synthetic.items()))
    (src / 'Module.symvers').write_text(text)
    (proof / 'synthetic-stock.Module.symvers').write_text(text)
    write_json(proof / 'synthetic-symbols.WARNING.json', {'abi_verified': False, 'zero_crcs': True,
               'inferred_builtin_owners_from_stock_undefined': inferred, 'stock_shared_exports': shared})
    run(['make', '-C', src, '-j' + str(os.cpu_count()), 'KBUILD_MODPOST_WARN=1', 'M=' + PAIR, 'modules'])
    check(sha(src / 'vmlinux') == thin_sha and sha(src / '.config') == CONFIG_SHA, 'thin ELF/config mutated')
    pair_symvers = src / PAIR / 'Module.symvers'
    check(pair_symvers.is_file(), 'missing real pair-only symvers')
    shutil.copyfile(pair_symvers, proof / 'pair.Module.symvers')
    bpftool_dir = ROOT / 'build/bpftool-modules-only'
    bpftool_dir.mkdir()
    run(['make', '-C', src / 'tools/bpf/bpftool', 'OUTPUT=' + str(bpftool_dir) + '/', 'bootstrap', '-j' + str(os.cpu_count())])
    bpftool = bpftool_dir / 'bootstrap/bpftool'
    check(bpftool.is_file(), 'missing source-matched bpftool')
    def dump_btf(path, label, split):
        args = [str(bpftool)] + (['-B', str(donor / 'base.btf')] if split else []) + ['btf', 'dump', 'file', str(path), 'format', 'raw']
        with gzip.GzipFile(filename=str(proof / (label + '.btf.txt.gz')), mode='wb', mtime=0) as stream:
            proc = subprocess.Popen(args, stdout=subprocess.PIPE)
            with proc.stdout:
                shutil.copyfileobj(proc.stdout, stream)
            check(proc.wait() == 0, 'BTF parse failed ' + label)
    dump_btf(donor / 'base.btf', 'official-base', False)
    pair_dir = output / 'pair'
    pair_dir.mkdir()
    metadata, imports = {}, {}
    for name, rel in base.MODULES.items():
        dest = pair_dir / (name + '.ko')
        shutil.copyfile(src / rel, dest)
        run(['strip', '--strip-debug', dest])
        metadata[name] = base.module_info(dest)
        check(metadata[name]['depends'] == sorted(['cfg80211', 'mac80211'] + (['ath12k'] if name == 'ath12k_wifi7' else [])), 'dependency metadata mismatch')
        check(metadata[name]['sha256'] != stock_records[name]['sha256'], 'unmodified stock pair member')
        dump_btf(dest, 'patched-' + name, True)
        _, undefined = elf_symbols(dest)
        imports[name] = {'symbols': sorted(undefined), 'not_observed_in_stock_pair': sorted(undefined - stock_imports),
                         'not_in_stock_or_pair_exports': sorted(undefined - set(synthetic) - set(pair_exports))}
        check(not imports[name]['not_in_stock_or_pair_exports'], 'new unresolved imports need explicit review')
    write_json(proof / 'pair-imports.json', imports)
    report = {'method': 'modules-only-experimental-v1', 'baseline_verified': False, 'hardware_tested': False,
              'full_kernel_build': False, 'full_baseline_reproduction': False, 'thin_btf_elf_only': True,
              'synthetic_stock_symvers': True, 'synthetic_stock_symvers_sha256': sha(proof / 'synthetic-stock.Module.symvers'),
              'module_symvers_scope': 'ath12k-pair-only', 'module_symvers_sha256': sha(pair_symvers),
              'source_commit': base.BASE, 'source_archive_sha256': SOURCE_SHA, 'config_sha256': CONFIG_SHA,
              'btf_vmlinux_sha256': BTF_SHA, 'toolchain': base.CACHE, 'patches': changes, 'modversions': False,
              'imports': imports, 'warning': 'NO full ABI proof. Wi-Fi failure/kernel crash/recovery outside plugin remain possible.'}
    write_json(proof / 'experimental-proof.json', report)
    shutil.copyfile(src / '.config', proof / 'official.config')
    inventory = run(['rpm', '-qa'], capture=True)
    (proof / 'rpm-inventory.txt').write_text('\n'.join(sorted(inventory.splitlines())) + '\n')
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for name in sorted(base.MODULES):
            data = (pair_dir / (name + '.ko')).read_bytes()
            entry = tarfile.TarInfo(name + '.ko')
            entry.size, entry.mode, entry.uid, entry.gid, entry.mtime = len(data), 0o644, 0, 0, 0
            archive.addfile(entry, io.BytesIO(data))
    bundle = output / 'pr594-only-7.2.6-aarch64.tgz'
    with bundle.open('xb') as stream:
        with gzip.GzipFile(filename='', mode='wb', fileobj=stream, mtime=0) as compressed:
            compressed.write(payload.getvalue())
    record = {'id': 'pr594-official-7-2-6-f1e136a-modules-only1', 'version': '0.1.0-experimental1',
              'patch_set': 'pr594-only', 'sha256': sha(bundle), 'system': json.loads((ROOT / 'target.json').read_text()),
              'stock_modules': stock_records, 'modules': metadata, 'deployment': {'mode': 'experimental-first-boot-v1'},
              'build': {'validation_level': 'modules-only-experimental-v1', 'baseline_verified': False,
                        'hardware_tested': False, 'modversions': False, 'module_symvers_scope': 'ath12k-pair-only',
                        'module_identity': 'sha256-gnu-build-id-v1', 'srcversion_all': False,
                        'source_commit': base.BASE, 'config_sha256': CONFIG_SHA, 'btf_vmlinux_sha256': BTF_SHA,
                        'module_symvers_sha256': sha(pair_symvers), 'experimental_proof_sha256': sha(proof / 'experimental-proof.json'),
                        'toolchain': base.CACHE, 'pr594_patch_sha256': [h for _, h in base.PATCHES]}}
    write_json(output / 'package-record.unpublished.json', record)
    (output / 'SHA256SUMS').write_text(sha(bundle) + '  ' + bundle.name + '\n')
    print('ACTUAL PAIR BUILT: EXPERIMENTAL, NO full ABI proof, NOT hardware tested, NOT installed.', flush=True)

if __name__ == '__main__':
    main()
