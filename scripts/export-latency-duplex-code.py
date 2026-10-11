"""Extend the source catalog from the exact received build; preserve every old binding."""
import argparse, hashlib, json, subprocess
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
def export(base):
    q = json.loads((base/'queue.json').read_text())
    catalog_path = WEB/'public/data/measurement-code.json'
    catalog = json.loads(catalog_path.read_text())
    commit = q['sourceCommit']; build = q['build']
    for kind in ['latency', 'duplex']:
        files = {}
        for part in ['main', 'kernel']:
            name = f'{kind}-{part}.cpp'; path = f'experiments/a5_latency_duplex/{name}'
            data = (WEB/path).read_bytes(); digest = hashlib.sha256(data).hexdigest()
            assert digest == build['sources'][name]
            assert subprocess.check_output(['git', 'show', f'{commit}:{path}'], cwd=WEB) == data
            catalog['files'][digest] = dict(path=path, sha256=digest, contentCommit=commit,
                url=f'https://github.com/Kirrito-k423/micro-benchmark-lab-web/blob/{commit}/{path}', text=data.decode())
            files[name] = digest
        binary = build['binaries'][f'build/{kind}-measure']
        assert binary not in catalog['builds'] or catalog['builds'][binary]['files'] == files
        catalog['builds'][binary] = dict(binarySha256=binary, files=files,
            recordedSourceCommit=commit, compileOptions=build['compileOptions'])
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, separators=(',', ':'))+'\n')
if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('base', type=Path); export(p.parse_args().base)
