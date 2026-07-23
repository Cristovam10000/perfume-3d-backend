# Hunyuan3D-2mv — Serviço de Inferência Docker

Serviço HTTP que expõe o pipeline [Hunyuan3D-2mv](https://github.com/deepbeepmeep/Hunyuan3D-2GP)
(fork low-VRAM por deepbeepmeep) para geração de modelos 3D GLB a partir de fotos de produtos.

## Pré-requisitos

- Docker Desktop com suporte a GPU (NVIDIA Container Toolkit)
- Driver NVIDIA ≥ 525 (host com CUDA 12.8+ suportado — CUDA 13.1 testado)
- RTX 5050 ou superior com ≥ 6GB VRAM livre

## Build

```bash
docker build -t perfume-hunyuan ./docker/hunyuan
```

O build usa `pytorch/pytorch:2.7.0-cuda12.8-cudnn9-devel`, porque algumas
dependências do Hunyuan compilam extensões CUDA durante a instalação e precisam
de headers como `cuda_runtime.h`.

O build inclui:
1. Clonagem do Hunyuan3D-2GP
2. Compilação do rasterizador customizado (requer `build-essential`)
3. Download dos pesos do pipeline de forma (~5GB) do HuggingFace

**Tempo estimado:** 20–40 minutos (dependendo da conexão e do cache Docker).

Para pular o download de pesos no build (download lazy no primeiro run), comente
o bloco `RUN python -c "..."` no Dockerfile.

## Execução

Via Docker diretamente:

```bash
docker run --gpus all -p 7860:7860 perfume-hunyuan
```

Via docker-compose (recomendado — inclui postgres e volume persistente):

```bash
# Na raiz do repositório backend (C:\TCC\perfume-3d-backend):
docker compose up hunyuan
```

## VRAM e performance (RTX 5050 8GB)

| Profile mmgp | VRAM pico | Tempo por modelo |
|---|---|---|
| 4 (padrão seguro) | ~6–8GB | 6–12 min |
| 3 | ~4–6GB | 10–18 min |
| 1/0 | pode passar de 8GB | mais rápido, mas arriscado na RTX 5050 |

O default usa o checkpoint de forma `tencent/Hunyuan3D-2mv` /
`hunyuan3d-dit-v2-mv`, `fp16`, e mantém a textura em
`tencent/Hunyuan3D-2`. O fallback single-view usa separadamente
`tencent/Hunyuan3D-2` / `hunyuan3d-dit-v2-0`, `fp16`. Além disso, usa
`octree_resolution=384`, `num_inference_steps=75`, `mc_algo=mc`,
`guidance_scale=7.5` e textura 2048 com tentativa multi-view. Na RTX 5050
8GB mantenha `MMGP_PROFILE=4`; teste `1`/`0` apenas se houver VRAM sobrando.

## Primeiro run sem pesos em cache

Se os pesos não estiverem no volume de cache, a inicialização faz download:
- Pipeline de forma multi-view (`tencent/Hunyuan3D-2mv`): ~5GB
- Pipeline de textura (hunyuan3d-paint): ~2GB

Os pesos são cacheados no volume `hunyuan_cache` (`/app/hf_cache` no container).
Para a forma, o servidor restringe o snapshot a `config.yaml` e
`model.fp16.safetensors`; isso evita baixar também a cópia legada `.ckpt` de
aproximadamente 5 GB.

## Teste do serviço

Com pesos em cache, a carga costuma levar cerca de 4–10 minutos, principalmente
enquanto o `mmgp` os organiza entre RAM e VRAM. No primeiro uso, acrescente o
tempo de download do `model.fp16.safetensors` (~5 GB); a duração total depende
da conexão. Aguarde o estado `ready`:

```bash
# 1. Verifica prontidão
curl http://localhost:7860/health
# → {"status":"ready","shape_mode":"multi-view",...,"fallback":false}

# 2. Gera modelo a partir de uma foto (substitua perfume.png por uma foto real)
curl -X POST http://localhost:7860/generate \
  -F "images=@perfume.png" \
  -F "octree_resolution=384" \
  -F "num_inference_steps=75" \
  -F "guidance_scale=7.5" \
  -F "mc_algo=mc" \
  -F "texture_resolution=2048" \
  --output modelo.glb

# Valida magic header do GLB
python3 -c "data=open('modelo.glb','rb').read(4); assert data==b'glTF', f'inválido: {data}'; print('GLB OK')"
```

Para múltiplas imagens (até 6):

```bash
curl -X POST http://localhost:7860/generate \
  -F "images=@frente.png" \
  -F "images=@lateral.png" \
  -F "images=@traseira.png" \
  --output modelo.glb
```

Para validar que o checkpoint correto foi carregado, confirme que o `/health`
mostra `shape_mode=multi-view`, `shape_repo=tencent/Hunyuan3D-2mv` e
`fallback=false`. `ready` com `single-view` continua funcional, mas indica modo
degradado: somente a primeira foto alimenta a geometria.

## Solução de problemas

### `CUDA error: no kernel image is available for execution on the device`

**Causa:** PyTorch sem suporte ao Blackwell (sm_120). A imagem base
`pytorch/pytorch:2.7.0-cuda12.8-cudnn9-devel` já inclui kernels sm_120.
Verifique se não usou uma imagem base diferente.

### `libGL.so.1: cannot open shared object file`

**Causa:** `libgl1` não instalado. Já está no Dockerfile; verifique se o build
completou sem erros (layer de apt).

### `custom_rasterizer` falha no build

**Causa:** falta de `build-essential` ou versão incompatível do compilador.
Verifique os logs do build. Em caso de falha, o modelo ainda funciona mas
sem textura de alta qualidade (fallback interno do Hunyuan).

### `Error loading model weights` / conexão HuggingFace recusada

**Causa:** firewall bloqueando o download. Defina `HF_HUB_OFFLINE=1` e use
pesos pré-baixados montados em volume, ou configure `HF_ENDPOINT` para um
mirror.

### `/health` mostra `shape_mode: single-view` e `fallback: true`

**Causa:** o checkpoint multi-view falhou e o servidor carregou o fallback.
Confira os logs e verifique se a configuração combina exatamente
`tencent/Hunyuan3D-2mv`, `hunyuan3d-dit-v2-mv` e `fp16`. O fallback fica em
`tencent/Hunyuan3D-2`, `hunyuan3d-dit-v2-0`, `fp16`.

### Container sai com `OOMKilled`

**Causa:** VRAM insuficiente. O servidor tenta fallback automático de `dmc`
para `mc` e de octree alta para `256`, mas se ainda falhar reduza
`octree_resolution`, use `HUNYUAN_ENABLE_TEXTURE=0` ou mantenha
`MMGP_PROFILE=4`.
