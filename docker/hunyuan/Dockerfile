# Imagem base oficial do PyTorch com CUDA 12.8 — necessário para suporte ao
# Blackwell (sm_120, RTX 5050). Foi usado a variante devel porque dependencias do
# Hunyuan (ex.: diso/custom rasterizer) compilam extensoes CUDA no build e
# precisam de headers como cuda_runtime.h.
FROM pytorch/pytorch:2.7.0-cuda12.8-cudnn9-devel

WORKDIR /app

ENV CUDA_HOME=/usr/local/cuda
ENV CPATH=/usr/local/cuda/targets/x86_64-linux/include:${CPATH}
ENV LIBRARY_PATH=/usr/local/cuda/targets/x86_64-linux/lib:${LIBRARY_PATH}
ENV LD_LIBRARY_PATH=/usr/local/cuda/targets/x86_64-linux/lib:${LD_LIBRARY_PATH}
# Docker build nao ve a GPU do host; sem isso torch tenta inferir a arquitetura
# pelas placas visiveis, recebe lista vazia e quebra ao compilar extensoes CUDA.
ENV TORCH_CUDA_ARCH_LIST=12.0

# Dependências de sistema para o Hunyuan3D + rasterizador customizado.
# libgl1/libglib2.0 são exigidos pelo OpenCV e pelo renderer diferenciável.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    libgl1 \
    libopengl0 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Clona o fork low-VRAM do Hunyuan3D-2 (deepbeepmeep/Hunyuan3D-2GP).
# O fork adiciona mmgp para offloading de pesos em GPUs < 16GB VRAM.
RUN git clone --depth 1 https://github.com/deepbeepmeep/Hunyuan3D-2GP.git /app/hunyuan
WORKDIR /app/hunyuan

# Patch: a versao nova do diffusers exige trust_remote_code=True ao carregar
# custom_pipeline local. O fork ainda nao inclui esse parametro em
# hy3dgen/texgen/utils/multiview_utils.py.
RUN sed -i 's|custom_pipeline=custom_pipeline_path, torch_dtype=torch.float16|custom_pipeline=custom_pipeline_path, torch_dtype=torch.float16, trust_remote_code=True|' \
    /app/hunyuan/hy3dgen/texgen/utils/multiview_utils.py && \
    grep -q "trust_remote_code=True" /app/hunyuan/hy3dgen/texgen/utils/multiview_utils.py || \
    (echo "PATCH FALHOU: trust_remote_code nao aplicado" && exit 1)

# Instala dependências do Hunyuan, excluindo torch/torchvision/torchaudio porque
# já estão na imagem base em versão compatível. Evita re-download de ~2GB
# desnecessário e possíveis conflitos de versão durante o build.
RUN grep -vE "^(torch|torchvision|torchaudio)" requirements.txt \
    > /tmp/requirements_hunyuan.txt && \
    pip install --no-cache-dir -r /tmp/requirements_hunyuan.txt

# Instala mmgp — biblioteca de offloading do deepbeepmeep para GPUs < 16GB.
RUN pip install --no-cache-dir mmgp

# Instala FastAPI + uvicorn para o servidor HTTP que expõe /health e /generate.
RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn[standard]>=0.32" "python-multipart>=0.0.20"

# Compila o rasterizador customizado do Hunyuan (necessário para texturização).
# Esse passo pode levar alguns minutos; erros aqui indicam falta de build-essential
# ou incompatibilidade de versão do compilador.
RUN cd hy3dgen/texgen/custom_rasterizer && pip install --no-cache-dir -e . && cd /app/hunyuan
RUN cd hy3dgen/texgen/differentiable_renderer && python setup.py install && cd /app/hunyuan

# Servidor HTTP que envolve o pipeline Hunyuan3D-2mv.
COPY server.py /app/server.py
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Pesos baixados lazy no primeiro /generate (evita timeout de rede no build).
# Para pre-baixar, descomente o bloco abaixo:
# ENV HF_HOME=/app/hf_cache
# RUN python -c "\
# from huggingface_hub import snapshot_download; \
# snapshot_download('tencent/Hunyuan3D-2', \
#     allow_patterns=['hunyuan3d-dit-v2-mv/*', 'hunyuan3d-dit-v2-0/*', 'hunyuan3d-vae-v2-0/*'])"
ENV HF_HOME=/app/hf_cache

EXPOSE 7860
ENTRYPOINT ["/app/entrypoint.sh"]
