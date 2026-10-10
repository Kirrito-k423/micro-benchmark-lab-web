"""Export immutable, receipt-matched source snapshots; never copy the latest kernel blindly.

Private inputs are read only. Public output contains source text, hashes and pinned
content links, without compiler paths, environment dumps or machine identities.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def sha(data):
    return hashlib.sha256(data).hexdigest()


def export(web, akl, network, private):
    data = {p.stem: json.loads(p.read_text()) for p in (web / 'public/data').glob('*.json') if p.stem != 'measurement-code'}
    catalog = dict(schema='akl.web.measurement-code.v1', files={}, builds={}, capacityRuns={})

    def snapshot(repo, path, expected, repo_url='https://github.com/Kirrito-k423/ascend-kernel-lab'):
        for commit in subprocess.check_output(['git', 'log', '--all', '--format=%H', '--', path], cwd=repo, text=True).splitlines():
            content = subprocess.check_output(['git', 'show', f'{commit}:{path}'], cwd=repo)
            if sha(content) != expected:
                continue
            catalog['files'][expected] = dict(path=path, sha256=expected, text=content.decode(), contentCommit=commit,
                url=f'{repo_url}/blob/{commit}/{path}')
            return expected
        raise ValueError(f'No immutable source matches receipt: {path} {expected}')

    def build(binary, repo, hashes, kernel, host=None, recorded_commit=None):
        selected = [kernel] + ([host] if host else [])
        if kernel == 'examples/a5_network/kernel.cpp' and 'examples/a5_network/shared_cq_completion.h' in hashes:
            selected.append('examples/a5_network/shared_cq_completion.h')
        files = {p: snapshot(repo, p, hashes[p]) for p in selected}
        catalog['builds'][binary] = dict(binarySha256=binary, files=files, recordedSourceCommit=recorded_commit)

    # Restore the older A3 variants using each run's manifest, matching both case
    # parameters and every published tick before binding a build to that run.
    d = data['datacopy']
    for run in sorted({r['run'] for r in d['rows'] if r['device'] == 'A3'}):
        mp = private / 'a3-capacity-20260924/results' / run / 'manifest.json'
        m = json.loads(mp.read_text())
        assert m['status'] == 'validated'
        cases = {c['case']['name']: c['case'] for c in m['cases']}
        for row in (r for r in d['rows'] if r['device'] == 'A3' and r['run'] == run):
            assert cases[row['case']['name']] == row['case']
            samples = json.loads((mp.parent / row['case']['name'] / 'samples.json').read_text())
            ticks = [str(s['ticks']) for s in samples if s['trace'] and not s['warmup']]
            assert ticks == row['rawTicks'] and all(s['correctness'] for s in samples)
        binary = m['build']['library_sha256']
        build(binary, akl, m['source_sha256'], 'kernels/datacopy.cpp')
        catalog['capacityRuns']['A3/' + run] = dict(build=binary, manifestSha256=sha(mp.read_bytes()), binding='case + all raw ticks matched to archived manifest')
    for run in d['provenance']['a5Runs']:
        binary = run['librarySha256']
        build(binary, akl, run['sourceSha256'], 'kernels/datacopy.cpp')
        catalog['capacityRuns']['A5/' + run['run']] = dict(build=binary, manifestSha256=run['manifestSha256'], binding='published receiver-validated manifest')

    m = data['a5-mbench']
    for binary in {r['libraryHash'] for r in m['alignment'] + m['alignmentPaired']}:
        build(binary, akl, m['evidence']['sources'], 'kernels/datacopy.cpp')
    for binary in {r['executableHash'] for r in m['simt']}:
        build(binary, akl, m['evidence']['sources'], 'examples/a5_mbench/simt_kernel.cpp', 'examples/a5_mbench/simt_main.cpp')
    for name, folder in [('a5-simd', 'a5_simd_mbench'), ('a5-bandwidth', 'a5_bandwidth')]:
        d = data[name]
        for binary in {r['binaryHash'] for r in d['rows']}:
            build(binary, akl, d['evidence']['sourceHashes'], f'examples/{folder}/kernel.cpp', f'examples/{folder}/main.cpp')
    d = data['a5-network']
    for binary, hashes in d['evidence']['measurementSourceSha256ByBinary'].items():
        hashes = {k.replace('src/', 'examples/a5_network/'): v for k, v in hashes.items()}
        commits = {r.get('sourceCommit') for r in d['rows'] if r['binarySha256'] == binary and r.get('sourceCommit')}
        assert len(commits) <= 1
        commit = next(iter(commits), d['evidence']['baselineSourceCommit'])
        for p, h in hashes.items():
            assert sha(subprocess.check_output(['git', 'show', f'{commit}:{p}'], cwd=network)) == h
        build(binary, network, hashes, 'examples/a5_network/kernel.cpp', 'examples/a5_network/main.cpp', commit)

    if 'a5-store-tail' in data:
        d = data['a5-store-tail']
        build(d['evidence']['binaryHash'], akl, d['evidence']['sourceHashes'],
              'examples/a5_store_tail/kernel.cpp', 'examples/a5_store_tail/main.cpp', d['evidence']['sourceCommit'])

    if 'a5-workset' in data:
        d = data['a5-workset']
        build(d['evidence']['binaryHash'], akl, d['evidence']['sourceHashes'],
              'examples/a5_bandwidth/kernel.cpp', 'examples/a5_bandwidth/main.cpp')

    if 'a5-peer-copy' in data:
        d = data['a5-peer-copy']
        for meta in d['evidence']['builds'].values():
            files = {p: snapshot(web, p, h, 'https://github.com/Kirrito-k423/micro-benchmark-lab-web') for p,h in meta['sources'].items()}
            catalog['builds'][meta['binaryHash']] = dict(binarySha256=meta['binaryHash'], files=files,
                recordedSourceCommit=None, compileOptions=meta['compileOptions'])

    if 'a5-page-retest' in data:
        for key,meta in data['a5-page-retest']['evidence']['sourceBindings'].items():
            files={}
            for path,h in meta['sources'].items():
                if h not in catalog['files']:
                    snapshot(web,'experiments/a5_page_retest/'+path,h,'https://github.com/Kirrito-k423/micro-benchmark-lab-web')
                    catalog['files'][h]['path']=path
                files[path]=h
            catalog['builds']['page-retest/'+key]=dict(binarySha256=meta['binaryHash'],files=files,recordedSourceCommit=None)

    if 'a5-extent' in data:
        for key,meta in data['a5-extent']['evidence']['sourceBindings'].items():
            files={path:snapshot(web,'experiments/a5_extent/'+path,h,
                'https://github.com/Kirrito-k423/micro-benchmark-lab-web') for path,h in meta['sources'].items()}
            catalog['builds'][meta['binaryHash']]=dict(binarySha256=meta['binaryHash'],files=files,
                recordedSourceCommit=None,compileOptions=meta['compileOptions'])

    out = web / 'public/data/measurement-code.json'
    out.write_text(json.dumps(catalog, ensure_ascii=False, separators=(',', ':')) + '\n')
    print(f'{len(catalog["builds"])} builds, {len(catalog["files"])} immutable source files; {out.stat().st_size} bytes')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--akl-root', type=Path, required=True)
    p.add_argument('--network-root', type=Path, required=True)
    p.add_argument('--private-results', type=Path, required=True)
    args = p.parse_args()
    export(Path(__file__).resolve().parents[1], args.akl_root, args.network_root, args.private_results)
