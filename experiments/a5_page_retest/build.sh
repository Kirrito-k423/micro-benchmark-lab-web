#!/usr/bin/env bash
set -euo pipefail
source /usr/local/Ascend/cann/set_env.sh
mkdir -p setup build-bandwidth build-tail
bisheng --version > setup/compiler.txt
cat "$ASCEND_HOME_PATH"/*-linux/ascend_toolkit_install.info > setup/cann.txt
cmake -S . -B build-a5 -DAKL_NPU_ARCH=dav-3510 -DCMAKE_BUILD_TYPE=Release
cmake --build build-a5 --target akl_datacopy -j2
for kind in bandwidth tail; do
 bisheng -O2 -g -c "$kind/main.cpp" -I"$ASCEND_HOME_PATH/include" -o "build-$kind/main.o"
 bisheng -O2 -g -xasc --npu-arch=dav-3510 -c "$kind/kernel.cpp" -I"$ASCEND_HOME_PATH/include" -o "build-$kind/kernel.o"
 bisheng "build-$kind/main.o" "build-$kind/kernel.o" --cce-fatobj-link -L"$ASCEND_HOME_PATH/lib64" -lascendcl -lruntime -o "build-$kind/measure"
done
PYTHONPATH=python python3 - <<'PY'
import json,hashlib
from pathlib import Path
from akl.native import Runtime
rt=Runtime(Path('build-a5/libakl_datacopy.so').resolve(),1,symbol='akl_copy',params_size=64)
try:hw=rt.info()
finally:rt.close()
plan=json.loads(Path('execution-plan.json').read_text())
assert hw['soc']==plan['expectedSoc'] and hw['aiv_count']==plan['availableAiv'] and hw['ub_bytes']==plan['ubBytes'],'Regenerate plan for actual hardware'
Path('setup/environment.json').write_text(json.dumps(hw,indent=2))
Path('setup/profile.json').write_text(json.dumps(dict(schema='akl.datacopy.profile.v1',soc=hw['soc'],npu_arch='dav-3510',topology='single_device_local_GM',memory_scope='local_GM',clock_hz=plan['clockHz'],clock_source=plan['clockSource']),indent=2))
files=[p for p in Path('.').rglob('*') if p.is_file() and any(str(p).startswith(x) for x in ['python/','include/','kernels/','scripts/','bandwidth/','tail/']) and '__pycache__' not in p.parts]
files += [Path('CMakeLists.txt'),Path('build.sh'),Path('run_stage.py'),Path('plan.py')]
meta=dict(schema='akl.page-retest.build.v1',sources={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},binaries={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path('build-a5/libakl_datacopy.so'),Path('build-bandwidth/measure'),Path('build-tail/measure')]},environment=hw,compiler=Path('setup/compiler.txt').read_text(),cann=Path('setup/cann.txt').read_text())
Path('setup/build.json').write_text(json.dumps(meta,indent=2))
print(json.dumps(hw))
PY
