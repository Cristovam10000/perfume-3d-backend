# 09d — Pré-processamento de Imagem (e o cleanup removido)

> **O que você vai aprender neste doc**
> - Por que o pré-processamento clássico (EXIF, white-balance, CLAHE) ainda vale a pena, mesmo com o front comprimindo a imagem.
> - Por que o estágio de **limpeza de malha foi removido do backend** e para onde ele migrou.
>
> **Pré-requisitos:** [09f - Pipeline integrado](09f-pipeline-integrado.md). O pré-processamento é o stage (1).

Camada defensiva na **entrada** do `IntegratedPipeline`: fotos de smartphone podem ter EXIF errado, luz mista e baixa nitidez. Segue o padrão Strategy: ABC + bypass `Disabled*` + implementação real.

| Stage | Posição no pipeline | Componente |
|---|---|---|
| Pré-processamento de imagem | (1) — antes de tudo | `StandardImagePreprocessor` |
| ~~Limpeza de malha~~ | removida em 2026-08 | migrou para o servidor Hunyuan |

A composição completa do pipeline está em [09f](09f-pipeline-integrado.md).

## ImagePreprocessor

Corrige problemas comuns de fotos de smartphone *antes* da remoção de fundo, para que o `BackgroundRemover` e o Hunyuan3D recebam entradas mais consistentes.

> **Por que ainda existe se o frontend "formata" a imagem?** O Flutter só aplica compressão JPEG (`imageQuality: 90` no `image_picker`). A implementação legada também possui análise ao vivo com `FrameAnalyzer`, mas o frontend **não** corrige EXIF, white balance, exposição, nitidez nem resolução. O preprocessamento clássico continua sendo responsabilidade do backend.

### O que faz, em ordem

| # | Etapa | Justificativa |
|---|---|---|
| 1 | EXIF auto-rotate | Fotos do iPhone/Android vêm com a tag de orientação; sem isso, frasco aparece deitado. Usa `PIL.ImageOps.exif_transpose` — solução canônica e barata. |
| 2 | White balance gray-world | Compensa tinte amarelo de luz incandescente, azul de sombra etc. Multiplica cada canal por (média_global / média_canal). Robusto, sem modelos. |
| 3 | CLAHE no canal L do LAB | Corrige sub-/superexposição local sem saturar cores. Aplicar CLAHE no RGB direto satura — em LAB, só o componente de luminância é tocado. |
| 4 | Sharpen condicional | Calcula Laplacian variance; se < `sharpen_threshold` (default 100), aplica unsharp mask. Foto já nítida não recebe sharpening (evita ruído amplificado). |
| 5 | Resize máx 2048 px | Hunyuan3D-2mv não consome mais que isso. Reduzir antes economiza VRAM e largura de banda. Mantém aspect ratio. |
| 6 | Save | PNG sem compressão se a saída terminar em `.png`; JPEG quality 95 caso contrário. |

### Parâmetros configuráveis

| Parâmetro | Default | Função |
|---|---|---|
| `white_balance` | `True` | Liga/desliga a etapa 2. Útil quando a luz já é controlada (estúdio). |
| `clahe_clip_limit` | `2.0` | Quanto mais alto, mais agressivo o CLAHE. Acima de 4.0 começa a "queimar" highlights. |
| `sharpen_threshold` | `100.0` | Variância de Laplacian abaixo disso = borrada → sharpen. Empírico: fotos de produto bem feitas dão >300, borradas dão <50. |
| `max_resolution` | `2048` | Lado maior do output. Reduzir para 1024 acelera o Hunyuan ao custo de detalhe. |

### Justificativa científica

Pré-processamento clássico (não neural) foi escolhido por três razões:

1. **Determinismo**: dois runs com a mesma foto produzem byte-igual. Importante para reproduzir resultados em defesa do TCC.
2. **Sem dependência de modelos**: nada para baixar, treinar ou versionar; o código depende só do OpenCV/Pillow.
3. **Custo computacional**: < 200 ms por foto no CPU. AWB neural ou deblur neural exigiriam GPU dedicada e adicionariam ~2–5 s por foto.

Onde isto falha — iluminação muito heterogênea (parte da foto na sombra forte, parte no sol), motion blur severo (>5 px), foco fora — uma rede neural ajudaria. Para o cenário de TCC (frasco fotografado em mesa com luz ambiente), a heurística é defensável.

### Encaixe no `IntegratedPipeline`

| Posição | Entrada | Saída | Falha |
|---|---|---|---|
| Stage (1) | `uploads/<job>/*.jpg` (cru, JPEG) | `tmp/<job>/preprocessed/*.jpg` | Degrade: pipeline cai para `DisabledImagePreprocessor` (cópia byte-a-byte) e segue. Loga warning. |

Se as fotos forem usadas como referência para extração de label (stage 7), o pipeline usa estas mesmas fotos preprocessadas — não as originais — para garantir consistência com a máscara do `BackgroundRemover`.

## MeshCleaner — removido em 2026-08

O estágio de limpeza de malha **não existe mais no backend**. `mesh_cleaner.py` e
`blender_scripts/cleanup_mesh.py` foram apagados, junto com as chaves
`MESH_CLEANER_TYPE` e `MESH_MIN_ISLAND_RATIO`.

A limpeza passou a ser responsabilidade exclusiva do **servidor Hunyuan**: o
`docker/hunyuan/server.py` aplica os pós-processadores nativos do hy3dgen
(`FloaterRemover` + `DegenerateFaceRemover`) **entre a geração de forma e a
texturização**, controlado por `HUNYUAN_SHAPE_POSTPROCESS` (default ligado).
Limpar lá é melhor do que limpar aqui: os floaters somem antes de receber
textura (não desperdiça paint) e a remoção usa a lógica do próprio Hunyuan.

O estágio local já vinha desligado (`MESH_CLEANER_TYPE=disabled`) porque a
validação manual mostrou que limpeza cega abria microfuros visíveis: o Hunyuan
pode gerar a superfície como milhares de "ilhas" adjacentes, e separar loose
parts / preencher furos / recalcular normais degradava o resultado. Ver
[16 - Auditoria do Blender](16-auditoria-blender.md).

> O `IntegratedPipeline` agora vai do stage (4) Hunyuan direto para o (5)
> `TransparencyClassifier`. O arquivo `cleaned.glb` deixou de ser produzido.

## Trade-offs

| Decisão | Alternativa | Por que essa? |
|---|---|---|
| Gray-world WB | Modelo de Retinex, AWB neural | Suficiente para luz mista comum; zero dependências adicionais. |
| CLAHE em L do LAB | CLAHE em RGB | LAB preserva matiz; RGB satura cores em fotos quentes. |
| Sharpen condicional via Laplacian | Sempre aplicar unsharp | Evita ruído amplificado em fotos já nítidas. |
| Limpeza no servidor Hunyuan | Estágio Blender no backend | Remove floaters antes da texturização e elimina um subprocess de ~20 s por job. |

## Limitações

- **Foto pré-processada não é foto de estúdio**: gray-world ainda erra em luz ambiente colorida (LED RGB, etc.). Para resultado profissional, usar AWB neural seria a evolução.
- **A limpeza saiu do controle do backend**: se o `HUNYUAN_SHAPE_POSTPROCESS` for desligado no contêiner, não há segunda camada. O `docker/hunyuan/server.py` não é versionado neste repositório.

## Uso manual

```bash
# Pré-processamento standalone (Python):
python -c "
import asyncio
from app.modules.captures.image_preprocessor import StandardImagePreprocessor
from pathlib import Path

async def main():
    p = StandardImagePreprocessor()
    await p.preprocess(Path('foto.jpg'), Path('foto_clean.jpg'))

asyncio.run(main())
"

```

Smoke histórico (cobertura legada, agora redundante com o pipeline integrado):

```bash
python scripts/smoke_phase4.py C:\imagens_Novas --open
```

Salva os artefatos intermediários em `storage/smoke/`:

- `preprocessed/*.jpg` — fotos após pré-processamento
- `masked/*.png` — após rembg
- `raw.glb` — saída do Hunyuan
- `cleaned.glb` — **cópia** de `raw.glb`; o passo `limpar_mesh()` virou passthrough quando o estágio foi removido, e o nome foi mantido só para preservar a numeração das fases do smoke
- `refined.glb` — após mesh refiner

Útil para abrir no model_viewer e validar etapa por etapa quando estiver depurando o pipeline.

## Leituras relacionadas

- [09b — Pipeline IA: Hunyuan3D-2mv](09b-pipeline-ai-hunyuan.md) (gera o `raw.glb`)
- [09c — Refinamento de Malha (shader de vidro)](09c-refinamento-mesh.md) (stage seguinte ao Hunyuan)
- [09e — Aplicação de Label](09e-aplicacao-label.md)
- [09f — Pipeline integrado](09f-pipeline-integrado.md) (composição)
- [10b — Segmentação e Label](10b-segmentacao-e-label.md) (`RembgBackgroundRemover` é stage 2)
- [16 — Auditoria do papel do Blender](16-auditoria-blender.md) (por que o cleaner saiu)
- Código:
  [`app/modules/captures/image_preprocessor.py`](../app/modules/captures/image_preprocessor.py)
- Smoke histórico:
  [`scripts/smoke_phase4.py`](../scripts/smoke_phase4.py)
