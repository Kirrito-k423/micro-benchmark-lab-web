#!/usr/bin/env bash
set -euo pipefail
source /usr/local/Ascend/cann/set_env.sh
mkdir -p build setup
bisheng --version > setup/compiler.txt
cat "$ASCEND_HOME_PATH"/*-linux/ascend_toolkit_install.info > setup/cann.txt
bisheng -O2 -g -c main.cpp -I"$ASCEND_HOME_PATH/include" -o build/main.o
bisheng -O2 -g -xasc --npu-arch=dav-3510 -c kernel.cpp -I"$ASCEND_HOME_PATH/include" -o build/kernel.o
bisheng build/main.o build/kernel.o --cce-fatobj-link -L"$ASCEND_HOME_PATH/lib64" -lascendcl -lruntime -o build/measure
python3 - <<'PY'
from pathlib import Path
import hashlib,json
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
names=['kernel.cpp','main.cpp','build.sh','plan.py','run_stage.py','README.md']
Path('setup/build.json').write_text(json.dumps(dict(schema='akl.extent.build.v1',sources={p:sha(p) for p in names},
    binaries={'build/measure':sha('build/measure')},compileOptions=['-O2','-g','-xasc','--npu-arch=dav-3510','--cce-fatobj-link'],
    compiler=Path('setup/compiler.txt').read_text(),cann=Path('setup/cann.txt').read_text()),indent=2))
PY
