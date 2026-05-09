# Sessão 2026-04-28 — Fases 4 e 5: pré-processamento de imagem, limpeza de malha e aplicação de label real

## 1. Metadados

- **Título:** Implementação simultânea das Fases 4 e 5 do pipeline IA — pré-processamento de fotos cruas (`ImagePreprocessor`), limpeza conservadora de malha vinda do Hunyuan3D (`MeshCleaner` + `cleanup_mesh.py`), upscale de label (`LanczosLabelUpscaler`), projeção de label real no GLB (`BlenderLabelProjector` + `project_label.py`), além dos smokes manuais `smoke_phase4.py` e `smoke_phase5.py`.
- **Data inferida pelos commits:** 2026-04-28 (commit principal `6e6f212`), com pequeno reforço em `df843ca` (2026-04-29) que adicionou parâmetros configuráveis ao `Hunyuan3DProcessor` no `smoke_phase5`.
- **Fase do projeto:** Fases 4 e 5 do pipeline IA, complementares às Fases 1–3 documentadas em `historico/2026-05-09_pipeline-ia-segmentacao-e-refinamento.md` (cuja data de arquivo é posterior, mas o conteúdo cobre commits de 2026-04-27).
- **Posicionamento cronológico inferido:** **terceira sessão de fato** dentro do conjunto, **logo após** a sessão das Fases 1–3 do pipeline IA. Pré-existia um *gap* documental: nenhum dos dois historicos prévios cobria explicitamente a entrega desta sessão. A sessão anterior (2026-05-09 no nome do arquivo, conteúdo de 2026-04-27) admitiu esse hiato em §7.3 ao listar `image_preprocessor.py`, `mesh_cleaner.py`, `label_projector.py`, `label_upscaler.py` como "artefatos não cobertos pela transcrição da conversa, pertencem a outras sessões".
- **Commits Git associados:**

    | Hash | Data | Mensagem | Notas |
    |---|---|---|---|
    | `6e6f212` | 2026-04-28 | `feat(captures): implement image preprocessing and mesh cleaning modules` | **Commit principal.** 18 arquivos / 3914 linhas inseridas / 2 modificadas. Cobre integralmente Fases 4 e 5. |
    | `df843ca` | 2026-04-29 | `feat(smoke): enhance Hunyuan3DProcessor with configurable parameters and error handling` | Reforço de UX no `smoke_phase5.py` — flags `--timeout-seconds`, `--octree-resolution`, `--num-inference-steps`, e `try/except` em `TimeoutException`. |
    | `724915c` | 2026-05-09 | `feat(sales): introduce sales module with repository, router, and schemas` | Tocou tangencialmente `scripts/smoke_phase3.py`, `scripts/smoke_phase4.py` e `scripts/smoke_phase5.py` (1–18 linhas cada) — ajustes pontuais. Escopo principal é o módulo `sales`, fora desta sessão. |

- **Sessões anteriores referenciadas:**
    - `historico/2026-04-26_fase2-templates-clip-cor.md` — Fase 2 (templates + CLIP + ColorDetector). Convenção do bypass `Disabled` (§3.5 daquele doc) é replicada em todas as quatro novas ABCs.
    - `historico/2026-05-09_pipeline-ia-segmentacao-e-refinamento.md` — Fases 1–3 do pipeline IA (background remover, label extractor, Hunyuan3D, mesh refiner). Esta sessão se *encaixa* no fluxo deixado no estado "fim de Fase 3" e *cumpre parcialmente* a pendência §7.2.1 daquele doc ("Fase 4 — composição do pipeline IA").

- **Esta sessão de chat (2026-05-09):** o chat de hoje invocou novamente um plano de "Fase 4". Como o git mostra que a Fase 4 já estava implementada em `6e6f212`, o efeito do chat foi uma **regeneração + validação** dos artefatos: arquivos foram reescritos com conteúdo equivalente ao já commitado, a suíte de 173 testes passou íntegra (1 skip por Hunyuan offline) e nenhum diff novo foi produzido contra `HEAD`. Detalhes no §5.6 deste doc.

## 2. Contexto inicial

Antes desta sessão (commit anterior `7990224` de 2026-04-27 e `a1b37ad` de 2026-04-27), o backend tinha:

- `BackgroundRemover` (rembg) e `LabelExtractor` (homografia OpenCV) implementados como componentes standalone.
- `Hunyuan3DProcessor` cliente HTTP do contêiner Docker, com `_FakeTransport` para testes unitários.
- `BlenderMeshRefiner` substituindo o material do corpo por shader de vidro PBR via `refine_ai_mesh.py`.
- `scripts/smoke_phase3.py` exercendo `rembg → Hunyuan → refiner` ponta a ponta.
- Suíte de ~146 testes verdes; container Docker do Hunyuan operacional.

O **diagnóstico empírico** restante após a Fase 3 (anotado em `historico/2026-05-09_pipeline-ia-segmentacao-e-refinamento.md` §7) listava três fragilidades que esta sessão resolve:

1. **Foto crua varia demais.** Smartphones produzem JPEG com EXIF heterogêneo, exposições muito ruins e branco descalibrado. O `BackgroundRemover` e o Hunyuan recebiam essa entrada bruta. Falta um passo determinístico de homogeneização antes da remoção de fundo.
2. **GLB do Hunyuan vem com bolinhas.** Validação manual revelou que o modelo gera ilhas soltas (artefato típico de geração com flow matching em octree), pequenos furos no topo da tampa e normais inconsistentes. O refinador trabalha o material, mas a geometria ainda é honesta.
3. **A textura da label gerada pelo Hunyuan é inutilizável para texto.** Modelos generativos de 3D inventam glyphs e borram detalhes pequenos. Para perfume — produto onde marca e nome são centrais — confiar no atlas do Hunyuan inviabiliza a entrega.

A motivação articulada no commit é: "*enhancing smartphone photos before 3D processing, correcting common issues like EXIF orientation, white balance, and exposure*" + "*remove artifacts from GLBs generated by AI, ensuring a cleaner mesh for further refinement*" + "*Implements `LabelProjector` and `LabelUpscaler` for applying and enhancing labels on 3D models*".

## 3. Decisões arquiteturais e de design

### 3.1 Verificação de continuidade com sessões anteriores

Esta sessão não revoga nenhuma decisão registrada em sessões anteriores. Em particular:

- **Confirma** o padrão Strategy + bypass `Disabled` da Fase 2 (`historico/2026-04-26 §3.5`) e da Fase 3 (`historico/2026-05-09 §3.5`). As quatro novas ABCs (`ImagePreprocessor`, `MeshCleaner`, `LabelUpscaler`, `LabelProjector`) seguem o molde.
- **Confirma** o padrão de subprocess Blender + `asyncio.to_thread` herdado do `TemplateProcessor` (Fase 2) e do `BlenderMeshRefiner` (Fase 3). Os dois novos scripts Blender (`cleanup_mesh.py`, `project_label.py`) seguem a mesma convenção: argumentos pós-`--`, `STATS:...` em stdout, `subprocess.run` com `PYTHONIOENCODING=utf-8`.
- **Não toca** em `service.py`, `main.py`, `config.py` nem nas factories. A integração das quatro novas peças no `CaptureService` é deferida explicitamente para a Fase 7.

### 3.2 Pré-processamento clássico (não neural)

A primeira pergunta de design foi: *deep learning ou clássico?* Trade-offs:

| Caminho | Custo | Qualidade |
|---|---|---|
| **Neural** (AWB neural, deblur GAN, SuperResolution) | +GPU, +modelos pré-treinados, +variabilidade entre runs | Melhor em casos extremos |
| **Clássico** (escolhido) | OpenCV + Pillow já presentes em `requirements-vision.txt` | Suficiente para fotos de smartphone "usáveis" |

A escolha pelo caminho clássico se justifica por três razões já registradas em `docs/09d-preprocessamento-e-cleanup.md`:

1. **Determinismo:** dois runs produzem byte-igual. Importante para reprodutibilidade na defesa do TCC.
2. **Sem dependências de modelos:** zero artefatos para baixar/versionar.
3. **Custo computacional:** < 200 ms por foto em CPU; AWB neural custaria 2–5 s e exigiria GPU dedicada.

A documentação assume explicitamente os limites: iluminação muito heterogênea (sombra forte + luz solar simultaneamente), motion blur > 5 px e foco fora ainda exigiriam modelos neurais. Para o cenário de TCC (frasco em mesa com luz ambiente), a heurística é defensável.

A ordem de operações foi pensada para evitar cascata destrutiva:

1. **EXIF auto-rotate** — antes de qualquer cv2, porque dimensões mudam.
2. **Gray-world WB** — antes do CLAHE, porque CLAHE não corrige tinte de iluminação.
3. **CLAHE no canal L do LAB** — explicitamente em LAB (não RGB) para preservar matiz; aplicar CLAHE no RGB satura cores em fotos quentes.
4. **Sharpen condicional via Laplacian variance** — só se variância < `sharpen_threshold` (default 100). Foto já nítida não é tocada (evita amplificar ruído).
5. **Resize máx 2048 px no maior lado** — Hunyuan3D-2mv não consome mais que isso; reduzir antes economiza VRAM e largura de banda.
6. **Save** — PNG (lossless) ou JPEG quality 95.

### 3.3 Limpeza de malha conservadora — sem remesh

`MeshCleaner` foi explicitamente projetado **sem remesh agressivo** (Voxel Remesh, Quad Remesher). Justificativa: remesh muda topologia inteira e perderia detalhes da label que o refinador da Fase 3 preserva. A política aceita é:

- Separar mesh por loose parts (componentes conexos).
- Calcular volume da bounding box de cada componente.
- Remover componentes com volume < `min_island_ratio × maior_volume`.
- Reagrupar sobreviventes em um único objeto via `bpy.ops.object.join`.
- Para cada mesh restante: `fill_holes(sides=4)`, `normals_make_consistent(inside=False)`, `shade_smooth` + `Auto Smooth 30°`.

**Decisão revisada após validação manual** (registrada na revisão pós-commit do `docs/09d`, citada em diff por linter): `min_island_ratio` default na chamada Python evoluiu de `0.05` para `0.0`. Em `0.0` o wrapper copia o GLB byte-a-byte sem invocar Blender. Motivo: em meshes reais do Hunyuan, a superfície vinha frequentemente como milhares de "ilhas" adjacentes por flutuação no octree, e a separação por loose parts abria microfuros visíveis ou demorava demais. Para artefatos claramente soltos, valores baixos (`0.005`–`0.01`) reativam o caminho Blender. **Padrão zero-cost por default; opt-in para limpeza efetiva.**

### 3.4 Volume de bbox como proxy de "tamanho" de ilha

A heurística usa volume de bounding box em vez de volume real (soma de tetraedros). Trade-off: volume real seria mais preciso, mas a diferença é inferior à variabilidade do critério. Bbox é barato, robusto a meshes não-fechados e não-orientáveis (que são justamente os casos onde a limpeza é necessária).

### 3.5 `fill_holes(sides=4)` — não fechar furos médios

Configuração intencional: `sides=4` fecha apenas furos de até 4 vértices no perímetro. Furos médios (5–10 vértices) permanecem abertos. Justificativa: o gargalo do frasco é um loop de borda grande e legítimo; fechá-lo seria erro pior que deixar furos médios abertos. O documento `docs/09d` registra explicitamente isso como limitação aceita.

### 3.6 STATS no stdout como contrato Blender↔Python

Seguindo o padrão da Fase 2, ambos os scripts Blender (`cleanup_mesh.py`, `project_label.py`) emitem uma linha estruturada em stdout:

- `cleanup_mesh.py` → `STATS:islands=N,holes=M,faces=K`
- `project_label.py` → `STATS:target_face_index=N,coverage_ratio=R`

Os wrappers Python parseiam via regex com fallback tolerante: se o `STATS:` não aparecer (script falhou após exportar), retornam zeros e logam `warning` em vez de levantar exceção. O GLB já existe; o caller decide se a falta de stats é problema.

### 3.7 Upscale Lanczos em vez de super-resolution neural

O `LanczosLabelUpscaler` aplica `Image.LANCZOS` da Pillow para ampliar a label extraída antes da projeção. A justificativa registrada no docstring do arquivo é central:

> "Lanczos não inventa detalhes como um super-resolution neural, mas evita nova dependência pesada e é suficiente quando a extração já tem algumas centenas de pixels."

Trade-off explícito: super-resolution neural (Real-ESRGAN, SwinIR) inventaria texto coerente onde a foto está borrada; Lanczos preserva borrão como borrão. Para um TCC focado em metodologia plugável, "preservar honestidade" da imagem capturada é mais defensável que "inventar nitidez". Real-ESRGAN é listado como pendência futura em `historico/2026-05-09 §7.2`.

### 3.8 Projeção de label como **decal frontal** com fallback geométrico

`BlenderLabelProjector` aplica a label como uma textura projetada na face frontal do frasco — não como atlas UV completo. O script `project_label.py` calcula:

1. A **face frontal** do mesh corpo via critério de área + orientação da normal (face com maior área cuja normal aponta para a câmera implícita do template).
2. Um **plano UV** sobre essa face com a aspect ratio da label upscaled.
3. Aplica a textura como `baseColorTexture` com mistura conservadora.

Quando a label não foi extraída (sem retângulo plausível na foto, p.ex. perfumes com texto direto no vidro), o `smoke_phase5.py` tem **fallback por recorte**: pega a região central/direita do frasco com maior densidade de bordas e usa como label substituta. Também aceita label manual via `--label-image caminho\label.png`. Ambos são heurísticas, mas o fallback mantém o pipeline funcional em vez de abortar.

### 3.9 Smokes separados por fase (4 e 5) em vez de um único smoke unificado

Decisão deliberada: `smoke_phase4.py` (preprocess + rembg + Hunyuan + cleanup + refiner) e `smoke_phase5.py` (idem + label_extractor + upscaler + projector) coexistem. Não houve reescrita de `smoke_phase3.py`. Motivo: cada fase entrega artefatos visualmente comparáveis lado a lado nos slides de defesa do TCC ("aqui o GLB cru", "aqui após cleanup", "aqui após cleanup + refiner", "aqui após cleanup + refiner + label real"). Apagar o smoke anterior perderia esse histórico comparativo.

### 3.10 Ajustes mínimos no `LabelExtractor` pré-existente

O `label_extractor.py` recebeu 40 linhas de modificação (adições) — pequenos refinamentos para tornar a saída compatível com o `LabelUpscaler`/`LabelProjector` sem quebrar contratos existentes da Fase 1. Detalhe omitido aqui por brevidade; auditável via `git diff 6e6f212^..6e6f212 -- app/modules/captures/label_extractor.py`.

## 4. Implementação realizada

### 4.1 Fase 4 — Pré-processamento de imagem e limpeza de malha

**Arquivos criados (commit `6e6f212`):**

- `app/modules/captures/image_preprocessor.py` (229 linhas) — `ImagePreprocessor` ABC + `DisabledImagePreprocessor` (cópia verbatim) + `StandardImagePreprocessor`. Lazy import de `cv2`/`PIL`/`numpy`. Validação de parâmetros no construtor (`clahe_clip_limit > 0`, `sharpen_threshold >= 0`, `max_resolution > 0`). Roda em `asyncio.to_thread`.
- `app/modules/captures/mesh_cleaner.py` (235 linhas) — `MeshCleaner` ABC + `MeshCleanupInput`/`MeshCleanupResult` (frozen dataclasses) + `MeshCleanupError` + `DisabledMeshCleaner` (copia GLB) + `BlenderMeshCleaner`. O wrapper Python segue o padrão de subprocess (`asyncio.to_thread` → `subprocess.run` com `PYTHONIOENCODING=utf-8`, parsing de STATS via regex).
- `app/modules/captures/blender_scripts/cleanup_mesh.py` (370 linhas) — script Blender headless. CLI: `--input`, `--output`, `--min-island-ratio`. Funções: `selecionar_unico`, `volume_bbox`, `contar_furos_pequenos` (BFS em arestas-borda para detectar loops fechados pequenos), `remover_ilhas_pequenas` (retorna objeto + n_ilhas_removidas), `fechar_furos_e_suavizar`, `aplicar_auto_smooth` (com fallback para Blender < 4.1), `contar_faces`. Compatível com Blender 5.1.
- `tests/modules/captures/test_image_preprocessor.py` (357 linhas) — 12 testes. `TestDisabledImagePreprocessor` (3): cópia byte-a-byte, criação de subdir, FileNotFoundError. `TestStandardImagePreprocessor` (9): validação de parâmetros, EXIF orientation 6 → dimensões trocadas, gray-world neutraliza tinte, CLAHE aumenta std do canal L em imagem subexposta, sharpen pulado quando Laplacian alto (mock), resize 4096×3072 → 2048×1536, aspect ratio preservado em proporção 3:1, resize ignorado se input já cabe, JPEG quality 95 via spy do `cv2.imwrite`.
- `tests/modules/captures/test_mesh_cleaner.py` (313 linhas) — 12 testes. `TestDisabledMeshCleaner` (3): cópia, byte-a-byte, missing input. `TestBlenderMeshCleanerMocked` (7): args incluem `--input/--output/--min-island-ratio`, parsing de STATS, STATS missing → zeros, returncode != 0, missing input GLB, ratio inválido, output não criado. `TestBlenderMeshCleanerIntegration` (2): Blender real com `rectangular_basic.glb` como stand-in, valida `glTF` magic + face count > 0; valida que pelo menos 1 mesh sobrevive.
- `scripts/smoke_phase4.py` (314 linhas) — pipeline 6 etapas com cronômetro: `(1/6) preprocess → (2/6) rembg → (3/6) Hunyuan → (4/6) cleanup → (5/6) refiner → (6/6) cópia para storage/smoke`. Salva intermediários em `storage/smoke/{preprocessed,masked,raw.glb,cleaned.glb,refined.glb}`. URLs do model_viewer impressas no final.
- `docs/09d-preprocessamento-e-cleanup.md` (208 linhas) — diagrama do pipeline, tabela de etapas com justificativas, tabela de parâmetros configuráveis, justificativa científica do caminho clássico, heurística de ilhas explicitada, trade-offs, limitações, uso manual.

### 4.2 Fase 5 — Aplicação de label real

**Arquivos criados (commit `6e6f212`):**

- `app/modules/captures/label_upscaler.py` (93 linhas) — `LabelUpscaler` ABC + `DisabledLabelUpscaler` (cópia) + `LanczosLabelUpscaler`. Aceita `target_size: int | None`. Lazy import de Pillow.
- `app/modules/captures/label_projector.py` (186 linhas) — `LabelProjector` ABC + `LabelProjectionInput`/`LabelProjectionResult` + `LabelProjectionError` + `DisabledLabelProjector` + `BlenderLabelProjector`. Mesmo padrão de subprocess do `BlenderMeshCleaner`. Parsing de `STATS:target_face_index=N,coverage_ratio=R`.
- `app/modules/captures/blender_scripts/project_label.py` (411 linhas) — script Blender headless. Identifica face frontal do corpo (área + orientação de normal), constrói plano UV, aplica textura como `baseColorTexture`. Detalhes específicos do material handling em Blender 4+.
- `tests/modules/captures/test_label_upscaler.py` (110 linhas) — testes de cópia (Disabled), upscale com target_size válido, preservação de aspect ratio, fallback se label menor que target.
- `tests/modules/captures/test_label_projector.py` (237 linhas) — testes mocked (args, retorno, falhas) + 1–2 testes de integração com Blender real.
- `scripts/smoke_phase5.py` (577 linhas) — pipeline 9 etapas: preprocess → rembg → label_extract (com fallback de recorte) → label_upscale → Hunyuan → cleanup → refine → label_project → cópia. Aceita `--label-image` para fornecer label manual.
- `docs/09e-aplicacao-label.md` (209 linhas) — justificativa de não usar a textura do Hunyuan, diagrama do sub-pipeline da label, fallback de recorte quando homografia falha.

### 4.3 Modificações em arquivos pré-existentes (no mesmo commit)

- `.gitignore` (+7 linhas) — provavelmente exclui `storage/smoke/*.glb` ou similar (commit não cita).
- `app/modules/captures/label_extractor.py` (+40 / -2 linhas) — refinamentos para compatibilidade com o pipeline da Fase 5.
- `tests/integration/test_hunyuan_real.py` (+9 linhas) — pequena adição (provavelmente nova fixture ou assert).
- `storage/model_viewer.html` (+11 linhas) — dropdown ou query string para alternar entre GLBs (`raw`, `cleaned`, `refined`, `with_label`).

### 4.4 Bibliotecas/dependências introduzidas

Não houve adição nova ao `requirements*.txt` neste commit. Todas as dependências já estavam em `requirements-vision.txt` da Fase 1: `opencv-python`, `pillow`, `numpy`, `rembg`. Isso é **deliberado**: o caminho clássico de pré-processamento foi escolhido, em parte, para não inflar dependências.

### 4.5 Reforço posterior (commit `df843ca`, 2026-04-29)

Pequena mas relevante revisão no `smoke_phase5.py`:

- Adicionados `--timeout-seconds`, `--octree-resolution`, `--num-inference-steps` como flags CLI.
- `try/except subprocess.TimeoutExpired` (e `httpx.TimeoutException`) com mensagens de erro em português explicando "Hunyuan excedeu timeout — aumente `--timeout-seconds` ou reduza `--octree-resolution`".

Justificativa: durante uso real do smoke, o tempo de inferência variava de 3 a 15 minutos dependendo da resolução do octree e do número de imagens. O timeout default de 600s era insuficiente em alguns casos. Em vez de hardcodar valor maior, parametrizou-se.

## 5. Problemas encontrados e soluções

### 5.1 `addWeighted` chamado mesmo com Laplacian alto no test mock

**Sintoma (reproduzido na sessão de chat 2026-05-09):** primeiro draft do teste `test_sharpen_skipped_when_image_already_sharp` montou um array `np.array([[1000.0]] * 10)` esperando que fosse o "Laplacian variance retornado". Mas `np.array([[1000.0]] * 10)` é um array 10×1 onde todas as células têm valor 1000.0; sua **variância** é 0 (todos iguais). O sharpening foi aplicado porque variance=0 < threshold=10.

**Solução:** alternar valores no array fake (`[0.0, 2000.0] * 50`) para forçar `.var()` retornar valor alto. Patch:

```python
laplacian_fake = np.array([0.0, 2000.0] * 50, dtype=np.float64).reshape(10, 10)
```

Aprendizado registrado: ao mockar resultado de função estatística, **garantir que a estatística esperada (variância, média, etc.) seja a desejada, não só os valores brutos**. Esse mesmo bug poderia ter passado despercebido em CI sem o assert explícito de `call_count == 0`.

### 5.2 `bpy.ops.mesh.separate(type='LOOSE')` falhando em mesh sem geometria

**Sintoma:** em meshes degenerados (vazios após import malformado), a operação `separate(type='LOOSE')` levanta `RuntimeError`. Sem tratamento, o script quebraria.

**Solução:** envolver em `try/except RuntimeError` e prosseguir. Caso o mesh não tenha geometria suficiente para separar, considera-se que já é uma "única ilha" trivial. Padrão aplicado também em `fill_holes` e `normals_make_consistent`.

### 5.3 `bpy.ops.object.shade_auto_smooth` removido em Blender < 4.1

**Sintoma:** Blender 4.1+ removeu `mesh.use_auto_smooth` e `mesh.auto_smooth_angle` em favor do operator `bpy.ops.object.shade_auto_smooth(angle=...)`. Em Blender 4.0 e anteriores, o operator não existe.

**Solução:** função `aplicar_auto_smooth` com fallback duplo:

```python
if hasattr(bpy.ops.object, "shade_auto_smooth"):
    bpy.ops.object.shade_auto_smooth(angle=angulo_rad)
else:
    obj.data.use_auto_smooth = True
    obj.data.auto_smooth_angle = angulo_rad
```

Documentado no comentário do método. Permite que o script rode em qualquer Blender 3.x ou 4.x sem detecção manual de versão pelo caller.

### 5.4 `min_island_ratio` agressivo demais em uso real

**Sintoma:** validação manual com GLBs reais do Hunyuan revelou que `min_island_ratio=0.05` (default original) gerava resultado pior — meshes vinham fragmentados em milhares de ilhas adjacentes por instabilidade do octree, e separar+reagrupar abria microfuros visíveis. O tempo do Blender também subia para 30+ segundos em meshes ruidosos.

**Solução:** mudar o default na chamada Python para `min_island_ratio=0.0`. Nesse modo, o wrapper copia o GLB byte-a-byte e nem invoca Blender — preserva o GLB cru do Hunyuan. Para artefatos claramente soltos, o usuário ajusta para `0.005`–`0.01` em modo opt-in. Documentação atualizada em `docs/09d` (linhas 86–93 da revisão pós-commit) explica a inversão.

### 5.5 `deploy.resources.reservations.devices` no docker-compose vs Docker Desktop

**Sintoma residual da Fase 2 (não desta sessão, mas mencionado em commit `a1b37ad` de 2026-04-27):** Docker Desktop no Windows nem sempre respeita `deploy.resources.reservations.devices` para passar GPU. Em alguns hosts era preciso `gpus: all` com versão antiga da CLI.

**Solução:** documentado no `docker/hunyuan/README.md`. Não foi tocado nesta sessão.

### 5.6 Sessão de chat 2026-05-09: regeneração com efeito nulo

**Sintoma observado na sessão de chat de hoje (2026-05-09):** o usuário invocou um plano de "Fase 4 — Image Preprocessing + Mesh Cleanup" como se fosse novo. O assistente seguiu o plano: criou `image_preprocessor.py`, `mesh_cleaner.py`, `cleanup_mesh.py`, `smoke_phase4.py`, testes e doc. A suíte de 173 testes passou (1 skip por Hunyuan offline).

**Diagnóstico:** o git mostra que o trabalho já existia em `6e6f212` desde 2026-04-28. Comparação `git diff HEAD` após a sessão: **zero diffs**. O conteúdo gerado pela sessão de chat ficou byte-idêntico ao commitado.

**Hipóteses:**

1. O usuário (ou linter) reverteu silenciosamente os Writes do assistente para o estado HEAD após cada operação.
2. O conteúdo prescrito no plano da sessão foi suficientemente determinístico para que a re-implementação produzisse arquivos idênticos.
3. Combinação das duas: arquivos no working tree já estavam no estado de HEAD; Writes do assistente foram normalizados pelo linter.

**Solução adotada:** documentar a sessão como "regeneração + validação" — não nova implementação. Os 173 testes verdes confirmam que a Fase 4 está estável; a sessão validou empiricamente esse estado e não introduziu regressões. Nenhum commit novo foi criado.

**Aprendizado metodológico:** sessões de chat futuras devem começar consultando `git log` antes de aceitar planos prescritivos do usuário. Implementar trabalho já commitado é desperdício de tokens e pode mascarar regressões reais quando o linter normaliza os outputs. Esse achado entra como pendência metodológica em §8.

## 6. Conceitos teóricos envolvidos

- **Pré-processamento clássico de imagem (gray-world WB, CLAHE em LAB, unsharp mask via Laplacian).** O *gray-world assumption* (Buchsbaum 1980) postula que a média global de uma cena natural deve tender ao cinza neutro; multiplicar cada canal pelo fator média_global/média_canal compensa tinte de iluminação. CLAHE (*Contrast Limited Adaptive Histogram Equalization*, Pizer et al. 1987) corrige contraste local em vez de global, evitando saturar regiões já bem expostas. A escolha de aplicar CLAHE no canal L do espaço LAB (Hunter 1948) preserva matiz; aplicar no RGB direto distorce cor. Unsharp mask via filtro Laplaciano detecta variância de bordas; alta variância = imagem nítida, baixa = borrada — heurística clássica para *blur detection* (Pertuz et al. 2013).

- **Segmentação geométrica por loose parts e bounding box volume.** Em malhas 3D, *connected components* (componentes conexos topologicamente, via aresta compartilhada) definem partes geometricamente independentes. Removê-los por volume da bbox é um filtro estatístico simples — uma forma de *outlier rejection*. Mais sofisticado seria volume real via *divergence theorem* (somatório de tetraedros), mas a melhoria empírica é marginal frente à variabilidade do critério.

- **Reconstrução de furos por triangulação local (`fill_holes`).** Operador clássico de processamento de malhas que detecta loops de borda fechados e tetragonaliza/triangulariza o polígono interno. Limitar `sides=4` é uma decisão de *minimum description length*: confiamos só em furos pequenos onde a geometria local é bem definida; furos médios podem ser legítimos (gargalo, abertura de design).

- **Recálculo de normais por consistência (`normals_make_consistent`).** Operador *flood-fill* sobre o grafo de adjacência de polígonos — propaga uma orientação inicial (escolhida por convenção: face de maior área, normal apontando para fora da bbox) para todas as faces vizinhas. Garante shading consistente em meshes manifoldes; em não-manifoldes, escolhe heuristicamente.

- **Auto Smooth com ângulo de 30°.** Em Blender, `Auto Smooth` divide as normais em arestas onde o ângulo diédrico excede o limiar. 30° é um valor empírico bem documentado: preserva quinas vivas (parede + ombro do frasco) sem suavizar artificialmente curvas suaves. Equivalente a *crease detection* em modelagem high-poly.

- **Lanczos resampling.** Filtro de reamostragem baseado em janela `sinc(πx) × sinc(πx/a)` (Duchon 1979) com lobo central e `a=3` lobos laterais. Comparado a bilinear/bicúbico, preserva melhor componentes de alta frequência sem introduzir aliasing. Para texto pequeno (label), Lanczos é o melhor entre os "não-neurais" — Real-ESRGAN seria a alternativa neural moderna mas a custo de determinismo e dependências.

- **Strategy Pattern (GoF) — quinta a oitava aplicação.** As ABCs `ImagePreprocessor`, `MeshCleaner`, `LabelUpscaler`, `LabelProjector` adicionam quatro novos pontos de plug ao mesmo padrão já aplicado em `Processor`, `Classifier`, `ColorDetector`, `BackgroundRemover`, `LabelExtractor`, `MeshRefiner`. O acúmulo de oito strategies sob a mesma forma constitui evidência forte (não apenas retórica) de que a abstração não é over-engineering: cada nova fase do pipeline encaixou naturalmente como nova ABC sem refatorar as anteriores.

- **Subprocess Blender + `STATS:` em stdout como protocolo IPC textual.** Padrão recorrente: o script Blender emite uma única linha estruturada em stdout que o wrapper Python parseia via regex tolerante. Mais simples que JSON-via-stdout (e Blender escreve muito mais texto que poderia interferir com parsing JSON). Equivalente a uma forma minimalista do padrão *structured logging* — útil quando o produtor é um processo externo cuja saída completa é "ruído + 1 linha que importa".

- **Determinismo como propriedade epistemológica.** A escolha repetida de heurísticas determinísticas (Lanczos vs SR neural; gray-world vs AWB neural; min-island por bbox vs deep mesh repair) é articulada em §3.2 e §3.7 como justificativa científica explícita, não só "não tinha tempo pra neural". Para um TCC, isso é argumentativamente forte: o sistema é reproduzível byte-a-byte sob re-execução, propriedade rara em pipelines com componentes ML.

## 7. Pendências e próximos passos

### 7.1 Pendências do documento `historico/2026-05-09_pipeline-ia-segmentacao-e-refinamento.md` (§7.2)

| Pendência registrada em 2026-05-09 (Fases 1-3) | Estado em 2026-04-28 (esta sessão) |
|---|---|
| 7.2.1 **Fase 4 — composição do pipeline IA.** Compor `BackgroundRemover` → `LabelExtractor` → `Hunyuan3DProcessor` → `BlenderMeshRefiner` no `CaptureService`. | 🔄 **Modificada/parcialmente cumprida.** Os componentes adicionais necessários para a composição (`ImagePreprocessor`, `MeshCleaner`, `LabelUpscaler`, `LabelProjector`) foram entregues como standalones com smoke manual ponta-a-ponta (`smoke_phase4.py`, `smoke_phase5.py`). A composição **dentro do `CaptureService`** continua deferida — agora para a Fase 7 explicitamente. |
| 7.2.2 **Validação visual real do refinador.** Critério "vidro transparente, label legível, materiais preservados" não exercido. | ⏳ **Ainda pendente.** O `smoke_phase4.py` e `smoke_phase5.py` exercem o pipeline ponta-a-ponta, mas a inspeção humana dos PNGs do `preview_refinement.py` ainda não foi documentada formalmente. |
| 7.2.3 **Suite de testes lentos em CI separado.** | ⏳ **Ainda pendente.** Os testes `slow` continuam manuais. Não há CI configurado. |
| 7.2.4 **Limitações conhecidas do Hunyuan documentadas mas não mitigadas.** Vidro/tampa/fundo. | 🔄 **Mitigadas em parte:** vidro tratado pelo refiner (Fase 3); fundo tratado pelo `BackgroundRemover` integrado nos smokes; tampa fundida ainda aberta (geometria inalterada, registrado em §3.3). |
| 7.2.5 **Caso de borda — refinador em GLB sem corpo identificável.** | ⏳ **Ainda pendente.** Sem teste de integração específico. |
| 7.2.6 **Pipeline de `LabelExtractor`: avaliação empírica.** | 🔄 **Parcialmente atendida.** O smoke_phase5 introduziu fallback por recorte quando a homografia falha (registrado em §3.8). Validação dos limites (5–60% de área, 0.3–3.0 aspect ratio, ≤35% de centralização) com lote real ainda pendente. |

### 7.2 Pendências do documento `historico/2026-04-26_fase2-templates-clip-cor.md` (§7.2)

| Pendência registrada em 2026-04-26 (Fase 2) | Estado em 2026-04-28 (esta sessão) |
|---|---|
| 7.2.1 Qualidade da classificação CLIP em casos reais. | ❌ **Não atendida.** Esta sessão não tocou em CLIP. A trilha IA torna o CLIP menos crítico para frascos novos, mas o problema permanece para o pipeline de templates. |
| 7.2.2 Segmentação de label (foto inteira como textura). | ✅ **Cumprida.** O `LabelExtractor` (Fase 1) + `LabelUpscaler` + `LabelProjector` (esta sessão) compõem a solução: extrai label retangular, aumenta com Lanczos, projeta como decal frontal no GLB. |
| 7.2.3 GLB para `feeling_rectangular_blue`. | ❌ **Não atendida**, mas tornada **menos crítica**: o Hunyuan3D infere o frasco azul-escuro retangular sem precisar do template. A entrada do catálogo CLIP segue inerte. |
| 7.2.4 Build GPU do PyTorch. | 🔄 **Contornada parcialmente:** PyTorch GPU está dentro do contêiner Docker do Hunyuan; o CLIP no host segue em CPU. |
| 7.2.5 Cor neutra para frascos brancos/transparentes. | ❌ **Não atendida.** `_chromatic_pixels` segue com fallback para média ingênua. |

### 7.3 Pendências geradas por esta sessão

1. **Fase 6 — material e HDRI customizados por template.** O refiner aplica vidro PBR genérico; ambientes diferentes (HDRI estúdio, cena de mesa, ambiente noturno) produziriam renders mais próximos da fotografia real do produto.
2. **Fase 7 — composição final no `CaptureService` + factories + `Settings`.** Integrar todos os componentes no pipeline operacional do worker, incluindo:
    - Roteamento entre `TemplateProcessor` e `Hunyuan3DProcessor` por flag de configuração ou por confiança do CLIP.
    - Decisão sobre quando aplicar `LabelExtractor` vs fallback de recorte vs label manual.
    - Configuração de `min_island_ratio` por job (default 0.0, override possível por header HTTP).
3. **Validação visual da Fase 5 com `preview_refinement.py` adaptado.** Hoje o script renderiza `before/after` apenas para o refinador. Versão estendida deveria gerar PNG comparativo de 4 estados: `raw`, `cleaned`, `refined`, `refined+label`. Útil para slides de defesa.
4. **Real-ESRGAN como `LabelUpscaler` opcional.** Trade-off documentado em §3.7; quando o trabalho de Fase 5 for considerado defensável academicamente, vale prototipar Real-ESRGAN como alternativa neural — mantendo Lanczos como default.
5. **Caso de borda do projetor:** quando o frasco do Hunyuan tem face frontal mal definida (geometria muito orgânica, ornamentos) ou quando duas faces têm área similar, `BlenderLabelProjector` pode escolher a errada. Documentado como limitação no `docs/09e`. Necessário benchmark com lote diverso.
6. **Aprendizado metodológico da sessão de chat 2026-05-09 (§5.6):** estabelecer convenção de "consultar git log antes de aceitar plano prescritivo do usuário" como instrução de sessão. Evita re-implementação cega de trabalho já commitado.

## 8. Reflexão para o TCC

### 8.1 Sobre a evolução do projeto

A combinação Fase 4 + Fase 5 num único commit revela uma escolha narrativa importante: **as duas fases são funcionalmente acopladas mesmo sendo logicamente separáveis**. Sem o `ImagePreprocessor`, o `LabelExtractor` falha em fotos com EXIF errado; sem o `MeshCleaner`, a geometria do refinador tem ilhas; sem o `LabelUpscaler`, a label projetada é pixelada. Implementar uma sem a outra produziria pipeline incompleto. O commit reflete essa realidade.

Isso é metodologicamente interessante: a divisão "Fase 4 vs Fase 5" é uma abstração de planejamento útil para decompor escopo, mas a execução natural foi conjunta. A documentação acadêmica pode argumentar honestamente que **a unidade de trabalho real foi "complementar a IA com pré- e pós-processamento clássicos"**, e que dividir em duas fases é organizacional, não técnico.

### 8.2 Mudanças de rumo em relação ao planejamento original

O plano original do TCC (Fase 1 = bootstrap, Fase 2 = templates+CLIP) tinha 2 fases. Após o diagnóstico empírico da Etapa 16 (Fase 2), o plano explodiu em 7+ fases organizadas em torno do pipeline IA. Esta sessão (Fases 4–5) é a continuação direta do que `historico/2026-05-09 §8.2` chamou de "bifurcação plugável sob a mesma abstração" — mas com um achado novo: **a IA generativa, sozinha, não basta**. Ela precisa de pré-processamento clássico para funcionar bem (Fase 4) e de complementos clássicos para entregar produto utilizável (Fase 5).

A síntese para a defesa: **modelos generativos cobrem o "centro do problema" (geometria 3D), mas as bordas (input cru variável, texto pequeno, artefatos numéricos) ainda exigem técnicas clássicas**. Esse é o argumento central do trabalho: pipeline híbrido onde clássico e neural se complementam, sob abstração plugável.

### 8.3 Aprendizados metodológicos

1. **A conjunção "duas fases num commit" é honesta.** O git captura unidades de trabalho; a documentação captura unidades de raciocínio. Quando elas divergem, o documento deve registrar a divergência — como este faz ao tratar Fases 4 e 5 num único historico.

2. **Heurísticas determinísticas merecem defesa explícita.** As múltiplas decisões "clássico em vez de neural" (gray-world, CLAHE, Lanczos, bbox volume) precisam de justificativa metodológica registrada — não basta dizer "era mais simples". A propriedade reproduzível byte-a-byte é argumento acadêmico de primeira ordem para um TCC com avaliadores que podem (e devem) re-executar o sistema.

3. **Default zero-cost em opções caras.** A inversão de `min_island_ratio` para `0.0` (§3.3 + §5.4) é uma forma de design responsável: quando uma opção é cara e seus benefícios são situacionais, o default deve ser bypass + opt-in. Evita penalizar usuários que não precisam da feature.

4. **Falsa-novidade em sessões de chat (§5.6).** Sessões de chat futuras devem auditar o git antes de aceitar planos prescritivos. Implementar trabalho já commitado consome tokens, polui o working tree e pode mascarar regressões reais quando o linter normaliza os outputs. Em projeto longitudinal de TCC, esse risco é real.

5. **Documentação que admite gaps é mais robusta.** O documento `historico/2026-05-09` admitiu em §7.3 a existência de artefatos cuja proveniência não conseguia rastrear. Esse hiato motivou diretamente este documento — ou seja, **honestidade documental gerou trabalho documental subsequente**. Padrão saudável para o TCC: ausências marcadas com `[verificar]` se transformam em pendências formais resolvidas em iterações posteriores.

---

*Documento gerado durante a sessão de chat de 2026-05-09 a partir de inspeção direta de `git show 6e6f212`, `git show df843ca`, do conteúdo atual do working tree (idêntico ao commit) e dos dois historicos pré-existentes. A sessão de chat em si (não esta documentação) é descrita como evento metadocumental em §5.6 e §7.3.6. Itens marcados `[verificar]` indicam pontos onde o estado do repositório no momento da redação não foi diretamente inspecionado e merecem confirmação manual antes de citação no texto final do TCC.*
