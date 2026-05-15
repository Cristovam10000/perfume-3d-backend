# 09c — Refinamento de Malha: Shader de Vidro PBR

Pós-processador do `IntegratedPipeline` que melhora visualmente os GLBs gerados pelo `Hunyuan3DProcessor`, substituindo o shader opaco do corpo do frasco por **vidro fisicamente correto**. Funciona como stage `(6)` na cadeia integrada (ver [09f](09f-pipeline-integrado.md)).

## O problema visual

O Hunyuan3D-2mv produz GLBs onde o "vidro" do frasco é um material **opaco azulado** — a IA interpreta as reflexões do ambiente como cor de superfície, pintando-as como textura.

O resultado bruto tem três características:

1. **Corpo opaco**: o vidro transparente vira uma superfície sólida com aparência plástica.
2. **Label boa**: a textura da label aplicada pela IA geralmente está usável (mas é substituída pelo decal real no stage seguinte — ver [09e](09e-aplicacao-label.md)).
3. **Tampa variável**: pode vir fundida ao corpo ou razoavelmente separada, dependendo do ângulo das fotos.

O `BlenderMeshRefiner` corrige o ponto 1 preservando o ponto 2 (a label já-aplicada é descartada depois pelo `LabelProjector`, mas o refiner deixa-a intacta).

## Visão geral

```
GLB do estágio anterior (cleaned.glb)
    └── BlenderMeshRefiner
            │  subprocess Blender headless
            │  refine_ai_mesh.py
            │
            ├── identificar_corpo_vidro()   → maior mesh sem Image Texture
            ├── aplicar_shader_vidro()      → Principled BSDF vidro PBR
            ├── detectar_tampa()            → best-effort por posição Z
            └── exportar GLB refinado
            ▼
    refined.glb (vidro transparente + label/tampa preservadas)
```

## Heurística: como o corpo é identificado

O script `refine_ai_mesh.py` usa dois critérios em sequência:

1. **Filtra labels**: descarta meshes cujo material tem `Image Texture → Base Color` (qualquer material com textura conectada ao Base Color é provavelmente label original do Hunyuan).
2. **Maior área**: dos candidatos restantes, seleciona o de maior área de superfície total (produto da soma das áreas das faces pelo fator de escala do objeto).

Se todos os materiais tiverem textura (caso raro em saídas do Hunyuan), o GLB é exportado sem alterações e um aviso é registrado.

## Parâmetros do shader de vidro

| Parâmetro | Valor | Justificativa |
|---|---|---|
| `IOR` | 1.45 | Índice de refração do vidro boro-silicato comum em perfumaria. |
| `Transmission Weight` | 1.0 | Transmissão total — frasco é transparente ao raio de luz. |
| `Roughness` | 0.05 | Vidro polido; valor > 0.1 produz aparência de vidro fosco. |
| `Base Color` | branco (1,1,1,1) | Sem tinte; cor percebida vem do líquido e do ambiente. |
| `Alpha` | 0.3 | Visibilidade parcial no preview Blender — não afeta exportação PBR. |

## Tampa (best-effort)

A tampa é identificada como o mesh sem textura de maior coordenada Z após a importação do glTF (que converte Y-up → Z-up no Blender). Só aplica o shader de plástico escuro se:

- O objeto está claramente acima do corpo (diferença Z > 20% da altura da bounding box).
- O material não tem textura (preserva tampas texturizadas intactas).

Se a heurística for inconclusiva, o mesh é ignorado sem erro.

## Limitações

- **Geometria não é alterada**: apenas materiais são substituídos. Imperfeições na malha (faces duplas, tampa fundida ao corpo) persistem após o refinamento. Limpeza geométrica é responsabilidade do `BlenderMeshCleaner` (ver [09d](09d-preprocessamento-e-cleanup.md)).
- **Cap detection fraca**: em frascos com tampa integrada ou muito próxima ao corpo, a heurística de posição Z não é conclusiva e a tampa é ignorada.
- **Frascos muito ornamentais**: se o frasco tiver muitas partes com área similar (ornamentos, gravações), o corpo pode ser identificado incorretamente.
- **Dependência do Blender**: requer Blender 5.1+ instalado na mesma máquina que o backend. Use a variável `BLENDER_EXECUTABLE` para apontar para a instalação correta.
- **Idempotência**: rodar o refinador duas vezes no mesmo GLB produz o mesmo resultado — o script remove conexões de textura existentes antes de aplicar os novos parâmetros.

## Encaixe no `IntegratedPipeline`

| Posição | Entrada | Saída | Falha |
|---|---|---|---|
| Stage (6) | `cleaned.glb` (do `BlenderMeshCleaner`) | `refined.glb` | Degrade: pipeline mantém `cleaned.glb` como entrada do stage (7) e loga warning. Não derruba o job. |

`liquid_color` pode ser passado para o refiner (`--liquid-color`) se o pipeline tiver essa informação (vindo do cache ou do `AverageColorDetector` se ele estiver ativo). Sem cor, o material `water` mantém o default do template/mesh.

## Uso manual (smoke test)

```bash
# Com qualquer GLB como entrada (ex: template normalizado como stand-in):
blender --background --python app/modules/captures/blender_scripts/refine_ai_mesh.py -- \
    --input assets/templates/normalized/rectangular_basic.glb \
    --output /tmp/refined.glb

# Com cor de líquido:
blender --background --python app/modules/captures/blender_scripts/refine_ai_mesh.py -- \
    --input raw_hunyuan_output.glb \
    --output refined.glb \
    --liquid-color "#4466AA"
```

## Visualização comparativa

O script `scripts/blender/preview_refinement.py` renderiza antes e depois lado a lado:

```bash
blender --background --python scripts/blender/preview_refinement.py -- \
    --before raw_hunyuan_output.glb \
    --after  refined.glb \
    --output comparison_before_after.png
```

Útil para slides de defesa do TCC.

## Leituras relacionadas

- [09b — Pipeline IA: Hunyuan3D-2mv](09b-pipeline-ai-hunyuan.md) (stage anterior — gera o GLB cru)
- [09d — Pré-processamento e cleanup](09d-preprocessamento-e-cleanup.md) (stage 5 — `cleaned.glb`)
- [09e — Aplicação de label](09e-aplicacao-label.md) (stage 7 — `with_label.glb`)
- [09f — Pipeline integrado](09f-pipeline-integrado.md) (composição completa)
- [09 — Pipeline 3D — templates (fallback)](09-pipeline-3d.md)
- Código: [`app/modules/captures/mesh_refiner.py`](../app/modules/captures/mesh_refiner.py)
- Script Blender: [`app/modules/captures/blender_scripts/refine_ai_mesh.py`](../app/modules/captures/blender_scripts/refine_ai_mesh.py)
- Preview comparativo: [`scripts/blender/preview_refinement.py`](../scripts/blender/preview_refinement.py)
