#!/bin/bash
set -e

export HF_HOME=${HF_HOME:-/app/hf_cache}
export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-0}

# Garante que o Python encontre o módulo hy3dgen (instalado em modo editable
# dentro do clone do Hunyuan3D-2GP).
export PYTHONPATH="/app/hunyuan:${PYTHONPATH}"

exec uvicorn server:app \
    --app-dir /app \
    --host 0.0.0.0 \
    --port 7860 \
    --log-level info
