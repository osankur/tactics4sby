#!/usr/bin/env bash
#
# Builds the pinned Yosys fork in vendor/yosys and installs its pyosys
# bindings into the environment that runs tactics4sby.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: scripts/install_yosys.sh [options]

Options:
  --python PATH     Interpreter whose environment receives pyosys
                    (default: .venv/bin/python, else python3)
  --pipx APP        Install pyosys into the pipx venv of APP instead
  --build-dir DIR   CMake build directory (default: .build/yosys)
  --jobs N          Parallel build jobs (default: nproc)
  --no-pyosys       Only build the yosys binary
  -h, --help        Show this help
EOF
}

root=$(git -C "$(dirname "${BASH_SOURCE[0]}")/.." rev-parse --show-toplevel)
yosys_dir="$root/vendor/yosys"
build_dir="$root/.build/yosys"
python=""
pipx_app=""
jobs=$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1)
install_pyosys=1

while [ $# -gt 0 ]; do
    case "$1" in
        --python|--pipx|--build-dir|--jobs)
            if [ $# -lt 2 ]; then
                echo "missing value for $1" >&2
                exit 2
            fi
            case "$1" in
                --python) python=$2 ;;
                --pipx) pipx_app=$2 ;;
                --build-dir) build_dir=$2 ;;
                --jobs) jobs=$2 ;;
            esac
            shift 2
            ;;
        --no-pyosys) install_pyosys=0; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

if [ -z "$python" ] && [ -z "$pipx_app" ]; then
    if [ -x "$root/.venv/bin/python" ]; then
        python="$root/.venv/bin/python"
    else
        python=$(command -v python3)
    fi
fi

git -C "$root" submodule update --init --recursive

cmake_opts=(-S "$yosys_dir" -B "$build_dir" -DCMAKE_BUILD_TYPE=Release)
if command -v ccache >/dev/null; then
    cmake_opts+=(-DCMAKE_CXX_COMPILER_LAUNCHER=ccache)
fi
cmake "${cmake_opts[@]}"
cmake --build "$build_dir" --target yosys yosys-abc --parallel "$jobs"

if [ "$install_pyosys" = 1 ]; then
    rev=$(git -C "$yosys_dir" rev-parse HEAD)
    if [ -n "$pipx_app" ]; then
        target="the pipx venv of $pipx_app"
        stamp="$build_dir/.pyosys-pipx-${pipx_app//\//_}"
        key="$rev:$pipx_app"
        pyosys_present() { pipx runpip "$pipx_app" show pyosys >/dev/null 2>&1; }
        pyosys_install() { pipx inject --force "$pipx_app" "$yosys_dir"; }
    else
        target=$python
        stamp="$build_dir/.pyosys-installed"
        key="$rev:$python"
        pyosys_present() { "$python" -m pip show pyosys >/dev/null 2>&1; }
        pyosys_install() {
            pip_opts=(--force-reinstall --no-deps)
            cmake_config="-DCMAKE_BUILD_TYPE=Release"
            if command -v ccache >/dev/null; then
                cmake_config+=" -DCMAKE_CXX_COMPILER_LAUNCHER=ccache"
            fi
            pip_opts+=(--config-settings "cmake=$cmake_config")
            "$python" -m pip install "${pip_opts[@]}" "$yosys_dir"
        }
    fi

    if [ -f "$stamp" ] && [ "$(cat "$stamp")" = "$key" ] && pyosys_present; then
        echo "pyosys for $rev is already installed in $target; skipping"
    else
        pyosys_install
        printf '%s' "$key" > "$stamp"
    fi
fi

"$build_dir/yosys" -V
"$build_dir/yosys" -p "help add" | grep -q -- "-not"

if [ "$install_pyosys" = 1 ] && [ -z "$pipx_app" ]; then
    "$python" -c 'from pyosys import libyosys as ys; assert hasattr(ys, "SigMap"), "pyosys lacks SigMap"; print(ys.yosys_maybe_version())'
fi

cat > "$root/.yosys-env" <<EOF
export YOSYS="$build_dir/yosys"
export PATH="$build_dir:\$PATH"
EOF
echo "Yosys built in $build_dir"
echo "Add it to the current shell with: source $root/.yosys-env"
