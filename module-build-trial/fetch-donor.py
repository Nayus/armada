#!/usr/bin/env python3
"""Fetch SHA256-pinned official kernel donor using anonymous, read-only OCI APIs."""
import gzip, hashlib, io, json, pathlib, subprocess, tarfile, urllib.request
ROOT = pathlib.Path(__file__).resolve().parent
REPO = 'armada-os/armada/pkg/kernel'
MANIFEST = 'sha256:c06d9f1ff3d961b5cee5f573fa688ac270e3ce38bae1a75270dba7bac70793a6'
LAYER = 'sha256:9875e765a60941113e85259c146ebe309c480748f3cdc94854281cc8e73343f1'
ARCHIVE_SHA = '48654f760ba3a143d1cd7678274e25e758eb8ca6d613713582e5ce0f4bcc0747'
IMAGE_SHA = 'f487338fb7570dd86a49f23797d573f7209648e05ccb2866f054f7ad2b373bf2'
CONFIG_SHA = '3cae56750274cbd5b90a788335389dfbd38ad9fcb526505593ee878dc208a04f'
BTF_SHA = '81399c2085e836a86095ce269a0df28e7d1c1ff6cc362806276e2f28672a2bd9'
def sha(data): return hashlib.sha256(data).hexdigest()
def main():
    output = ROOT / 'donor'
    output.mkdir(exist_ok=False)
    token = json.load(urllib.request.urlopen('https://ghcr.io/token?service=ghcr.io&scope=repository:' + REPO + ':pull'))['token']
    def fetch(path, expected):
        req = urllib.request.Request('https://ghcr.io/v2/' + REPO + '/' + path, headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.v2+json'})
        with urllib.request.urlopen(req, timeout=180) as response: data = response.read()
        if 'sha256:' + sha(data) != expected: raise ValueError('OCI digest mismatch')
        return data
    manifest_bytes = fetch('manifests/' + MANIFEST, MANIFEST)
    manifest = json.loads(manifest_bytes)
    (output / 'package-manifest.json').write_bytes(manifest_bytes)
    config = fetch('blobs/' + manifest['config']['digest'], manifest['config']['digest'])
    (output / 'package-config.json').write_bytes(config)
    if json.loads(config)['architecture'] != 'arm64': raise ValueError('wrong architecture')
    if [x['digest'] for x in manifest['layers']] != [LAYER]: raise ValueError('unexpected layers')
    layer = fetch('blobs/' + LAYER, LAYER)
    with tarfile.open(fileobj=io.BytesIO(layer), mode='r:*') as archive:
        members = [x for x in archive.getmembers() if x.isfile() and x.name.endswith('/armada-kernel-7.2.6.tar.zst')]
        if len(members) != 1: raise ValueError('kernel package not unique')
        payload = archive.extractfile(members[0]).read()
    if sha(payload) != ARCHIVE_SHA: raise ValueError('kernel archive mismatch')
    package = output / 'armada-kernel-7.2.6.tar.zst'
    package.write_bytes(payload)
    proc = subprocess.Popen(['zstd', '-dc', str(package)], stdout=subprocess.PIPE)
    inventory = {}
    with tarfile.open(fileobj=proc.stdout, mode='r|') as archive:
        seen = set()
        for member in archive:
            name = member.name.removeprefix('./')
            path = pathlib.PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or name in seen: raise ValueError('unsafe/duplicate archive path')
            seen.add(name)
            if member.isdir(): continue
            if not member.isfile(): raise ValueError('nonregular archive member: ' + name)
            if not name.startswith('lib/modules/7.2.6/'): raise ValueError('unexpected archive member')
            data = archive.extractfile(member).read()
            destination = output / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            inventory[name] = sha(data)
    if proc.wait() != 0: raise ValueError('zstd decompression failed')
    image = (output / 'lib/modules/7.2.6/vmlinuz').read_bytes()
    if sha(image) != IMAGE_SHA: raise ValueError('Image mismatch')
    btf = image[43180032:43180032+8742475]
    if sha(btf) != BTF_SHA: raise ValueError('base BTF mismatch')
    (output / 'base.btf').write_bytes(btf)
    marker = b'IKCFG_ST'
    start = image.find(marker)
    if start < 0 or image.find(marker, start + 1) != -1: raise ValueError('IKCONFIG not unique')
    end = image.find(b'IKCFG_ED', start)
    if end < 0: raise ValueError('IKCONFIG end missing')
    config = gzip.decompress(image[start+len(marker):end])
    if sha(config) != CONFIG_SHA: raise ValueError('IKCONFIG mismatch')
    (output / 'official.config').write_bytes(config)
    (output / 'inventory.json').write_text(json.dumps(inventory, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'official_donor_extracted': True, 'files': len(inventory), 'config_sha256': sha(config), 'btf_sha256': sha(btf), 'generated_build_tree_present': False}))
if __name__ == '__main__': main()
