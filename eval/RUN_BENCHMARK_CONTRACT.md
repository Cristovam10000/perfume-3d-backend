# Contrato CLI uniforme: `run_benchmark.py`

Para o orquestrador conseguir invocar **qualquer branch** sem conhecer os
detalhes do pipeline daquela branch, cada uma precisa expor um script
**com a mesma interface CLI**. Esse documento define essa interface.

## Localização

Cada branch coloca seu script em:

```
back/run_benchmark.py
```

(Não em `back/scripts/`, nem em `back/app/`. Diretamente em `back/` —
ponto de entrada uniforme.)

## Invocação

```
python run_benchmark.py \
  --views-dir   PATH    # diretório com {front,left,back,right}.png
  --output-glb  PATH    # caminho exato onde salvar o GLB resultante
  [--timeout SECONDS]   # default: 1800 (30 min)
  [--verbose]           # logs extras em stderr
```

## Comportamento esperado

1. **Lê** as imagens em `--views-dir`. Cada branch escolhe quais usar:
   - **IA / Blander**: leem só as 4 cardeais (`front.png`, `left.png`,
     `back.png`, `right.png`). Se alguma faltar, falham com exit != 0.
   - **Meshroom**: lê **todas** as imagens disponíveis (cardeais + qualquer
     `orbit_*.png` que o orquestrador tenha gerado). Fotogrametria precisa
     de cobertura densa; o orquestrador renderiza 4 cardeais + 24 orbit por
     default = 28 vistas pro Meshroom contra 4 pras outras.
2. **Roda** o pipeline daquela branch (Blender / Meshroom / Hunyuan).
3. **Escreve** o GLB em `--output-glb` (cria diretórios pais se preciso).
4. **Sai com exit code 0** em sucesso, != 0 em falha.

### Justificativa da assimetria de input

A pergunta natural é: "não é injusto Meshroom ter 28 vistas e os outros 4?".
A resposta: **cada método é avaliado no input que ele foi projetado para
receber**. Hunyuan3D-2mv foi treinado em 4 vistas cardeais; alimentá-lo
com 28 não ajuda (o checkpoint só aceita 4). Meshroom precisa de cobertura
fotogramétrica para SfM funcionar; alimentá-lo com 4 vistas o garante a
falhar — não é teste de qualidade, é teste de incompatibilidade. Comparar
"melhor desempenho de cada um" é mais honesto que "pior desempenho de
Meshroom". A monografia deve explicitar essa assimetria no capítulo de
metodologia.

## Output em stdout (JSON, uma linha)

Sucesso:

```json
{"status":"ok","glb":"C:/TCC_eval_data/outputs/ia/perfume_001.glb","duration_s":42.1,"peak_vram_mb":2100}
```

Falha:

```json
{"status":"error","error":"Hunyuan retornou HTTP 500","duration_s":12.3}
```

Os campos `duration_s` e `peak_vram_mb` são para o CSV de métricas de
processo. `peak_vram_mb` pode ser `null` se a branch não medir.

## Exit codes

| Code | Significado |
|---|---|
| 0 | Sucesso, GLB escrito |
| 1 | Erro genérico (pipeline falhou) |
| 2 | Input inválido (PNGs faltando) |
| 124 | Timeout |

## Implementação por branch

### Branch `IA` (Hunyuan)

```python
# back/run_benchmark.py (IA branch)
"""Invoca o IntegratedPipeline em 4 vistas e salva o GLB.

Sobe o backend NÃO é necessário — chamamos o Processor diretamente.
"""
import argparse
import json
import sys
import time
from pathlib import Path

from app.main import build_pipeline
from app.modules.captures.processor import ProcessingInput
from app.storage.local_storage import LocalStorage

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--views-dir", type=Path, required=True)
    p.add_argument("--output-glb", type=Path, required=True)
    p.add_argument("--timeout", type=float, default=1800)
    args = p.parse_args()

    views = ["front", "left", "back", "right"]
    image_paths = [args.views_dir / f"{v}.png" for v in views]
    for img in image_paths:
        if not img.exists():
            print(json.dumps({"status":"error","error":f"missing {img.name}"}))
            sys.exit(2)

    storage = LocalStorage(root=args.output_glb.parent / ".tmp_storage")
    pipeline = build_pipeline(storage=storage)
    args.output_glb.parent.mkdir(parents=True, exist_ok=True)

    start = time.monotonic()
    try:
        import asyncio
        asyncio.run(pipeline.process(ProcessingInput(
            job_id=args.output_glb.stem,
            image_paths=image_paths,
            output_path=args.output_glb,
            views=views,  # rotulagem direta (LabeledViewRouter)
        )))
    except Exception as exc:
        print(json.dumps({"status":"error","error":str(exc),
                          "duration_s":time.monotonic()-start}))
        sys.exit(1)
    print(json.dumps({"status":"ok","glb":str(args.output_glb),
                      "duration_s":time.monotonic()-start,
                      "peak_vram_mb":None}))

if __name__ == "__main__":
    main()
```

### Branch `Blander`

Recebe as 4 vistas, roda CLIP classifier pra escolher template,
customiza com Blender. Resultado: a vantagem in-distribution dele
deve evidenciar o bias na tabela.

### Branch `Meshroom`

Recebe as 4 vistas, monta a estrutura esperada pelo Meshroom (pasta
de imagens), invoca o `meshroom_batch.exe`, recupera o GLB exportado.

## Por que não usar HTTP?

Considerado e descartado:

- **HTTP exige 3 backends rodando simultaneamente** (memória pesada).
- **HTTP esconde tempos reais** (overhead de upload, fila assíncrona).
- **CLI direto** te dá `time.monotonic()` honesto e stack trace cru
  quando algo quebra.
- **CLI é reprodutível** — qualquer um (banca, professor) pode rodar
  cada script em separado.

## Como o orquestrador chama

```python
# em c:\TCC\back\eval\benchmark.py (branch IA, mas orquestra todas)
def run_branch(branch_name: str, worktree: Path, views_dir: Path, out_glb: Path):
    python_exe = worktree / "back" / ".venv" / "Scripts" / "python.exe"
    script = worktree / "back" / "run_benchmark.py"
    result = subprocess.run(
        [str(python_exe), str(script),
         "--views-dir", str(views_dir),
         "--output-glb", str(out_glb)],
        capture_output=True, text=True, timeout=1800,
    )
    if result.returncode != 0:
        return {"status":"error","branch":branch_name,
                "exit_code":result.returncode,
                "stderr":result.stderr[-1000:]}
    return json.loads(result.stdout.strip().splitlines()[-1])
```
