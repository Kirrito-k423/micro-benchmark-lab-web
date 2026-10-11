#!/usr/bin/env bash
set -euo pipefail
source /usr/local/Ascend/cann/set_env.sh
mkdir -p build setup
bisheng --version > setup/compiler.txt
cat "$ASCEND_HOME_PATH"/*-linux/ascend_toolkit_install.info > setup/cann.txt
for kind in latency duplex; do
 bisheng -O2 -g -c "$kind-main.cpp" -I"$ASCEND_HOME_PATH/include" -o "build/$kind-main.o"
 bisheng -O2 -g -xasc --npu-arch=dav-3510 -c "$kind-kernel.cpp" -I"$ASCEND_HOME_PATH/include" -o "build/$kind-kernel.o"
 bisheng "build/$kind-main.o" "build/$kind-kernel.o" --cce-fatobj-link -L"$ASCEND_HOME_PATH/lib64" -lascendcl -lruntime -o "build/$kind-measure"
done
python3 - <<'PY'
from pathlib import Path
import hashlib,json
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
sources=['latency-main.cpp','latency-kernel.cpp','duplex-main.cpp','duplex-kernel.cpp','build.sh','run_stage.py','plan.py','README.md']
Path('setup/build.json').write_text(json.dumps(dict(schema='akl.latency-duplex.build.v1',sources={p:sha(p) for p in sources},
 binaries={f'build/{k}-measure':sha(f'build/{k}-measure') for k in ['latency','duplex']},
 compileOptions=['-O2','-g','-xasc','--npu-arch=dav-3510','--cce-fatobj-link'],
 compiler=Path('setup/compiler.txt').read_text(),cann=Path('setup/cann.txt').read_text()),indent=2)+'\n')
PY
