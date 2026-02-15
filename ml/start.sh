#!/bin/bash
set -e

VENV_DIR="/cache/venv"
MARKER="$VENV_DIR/.installed"

install_deps() {
    echo "=== Installing dependencies (first run — this may take a few minutes) ==="

    python3 -m venv "$VENV_DIR"
    source "$VENV_DIR/bin/activate"

    # Detect CUDA
    if python3 -c "import ctypes; ctypes.CDLL('libcuda.so.1')" 2>/dev/null; then
        echo "CUDA detected — installing PyTorch with GPU support"
        TORCH_INDEX="https://download.pytorch.org/whl/cu128"
    else
        echo "No CUDA — installing PyTorch CPU-only"
        TORCH_INDEX="https://download.pytorch.org/whl/cpu"
    fi

    pip install --no-cache-dir \
        torch --index-url "$TORCH_INDEX"

    pip install --no-cache-dir \
        panns_inference \
        fastapi \
        "uvicorn[standard]"

    touch "$MARKER"
    echo "=== Dependencies installed ==="
}

if [ ! -f "$MARKER" ]; then
    install_deps
else
    echo "Dependencies already installed (cached in volume)"
    source "$VENV_DIR/bin/activate"
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8769
