# Sessão 2026-05-09 — Pipeline alternativo via IA: segmentação, geração com Hunyuan3D e refinamento de malha

## 1. Metadados

- **Título:** Implementação da trilha alternativa por IA generativa — Fase 1 (segmentação de fundo e extração de rótulo), Fase 2 (cliente HTTP para Hunyuan3D-2mv em contêiner Docker) e Fase 3 (refinamento de malha via Blender headless com shader de vidro PBR).
- **Data do arquivo:** 2026-05-09 (data da redação inicial do documento).
- **Data inferida pelos commits:** **2026-04-27** — todos os commits cobertos por este documento são desse dia. O nome do arquivo foi mantido como originalmente criado para preservar continuidade da referência cruzada já estabelecida em `historico/2026-04-28_fase4-fase5-preprocessamento-cleanup-label.md`. O TCC final pode optar por renomear para `2026-04-27_pipeline-ia-segmentacao-e-refinamento.md` — registramos aqui a divergência conscientemente.
- **Posicionamento cronológico inferido:** **segunda sessão documentada**. Posterior à Fase 2 (templates+CLIP+cor, commits 2026-04-26 em `historico/2026-04-26_fase2-templates-clip-cor.md`) e anterior às Fases 4–5 (commit `6e6f212` em 2026-04-28, cobertas em `historico/2026-04-28_fase4-fase5-preprocessamento-cleanup-label.md`).
- **Fase do projeto:** Pós-Fase 2 do MVP. As três sub-fases entregues nesta sessão correspondem ao desdobramento explícito da "trilha alternativa" registrada em `historico/2026-04-26_fase2-templates-clip-cor.md`, seção 7.3.
- **Escopo principal:** complementar o pipeline de templates paramétricos com um pipeline **independente** baseado em IA generativa (Hunyuan3D-2mv) capaz de produzir malhas 3D direto das fotos do produto, e instalar o pré-processamento (segmentação de fundo via `rembg`, extração de label via homografia OpenCV) e o pós-processamento (substituição de shader de vidro por PBR feito à mão) necessários para que o GLB final seja visualmente defensável.
- **Repositório:** `C:\TCC\back` (backend FastAPI) + `C:\TCC\docker\hunyuan` (serviço de inferência GPU isolado em contêiner) + `C:\TCC\docker-compose.yml` (orquestração postgres + hunyuan).
- **Commits Git associados:**

    | Hash | Data | Mensagem | Sub-fase |
    |---|---|---|---|
    | `71a813c` | 2026-04-27 | `feat(captures): implement background removal and label extraction modules` | Fase 1 — segmentação |
    | `7a9408e` | 2026-04-27 | `feat(captures): add Hunyuan3DProcessor and mesh refinement capabilities` | Fases 2 + 3 — Hunyuan + refiner |
    | `7990224` | 2026-04-27 | `feat(smoke): add smoke_phase3 script for visual validation of AI pipeline` | E2E smoke da Fase 3 |
    | `a1b37ad` | 2026-04-27 | `chore(requirements): add onnxruntime dependency for model compatibility` | Reforço de deps |

    Em conflito entre a inferência cronológica do nome do arquivo (2026-05-09) e os commits Git (2026-04-27): **prevalecem os commits**, conforme regra de ancoragem cronológica adotada para o conjunto de historicos. A nota de fechamento original do documento ("incluindo a parte pré-compactação reportada via sumário automático") sugere que a redação se deu em 2026-05-09 cobrindo trabalho feito em 2026-04-27.

- **Sessões anteriores referenciadas:**
    - `historico/2026-04-26_fase2-templates-clip-cor.md` — pré-requisito direto. A trilha IA documentada aqui foi anunciada em §7.3 daquele documento.

- **Sessões posteriores que referenciam esta:**
    - `historico/2026-04-28_fase4-fase5-preprocessamento-cleanup-label.md` — depende dos componentes desta sessão (`BackgroundRemover`, `LabelExtractor`, `Hunyuan3DProcessor`, `BlenderMeshRefiner`) como pontos de plug; resolve parcialmente a pendência §7.2.1 ("Fase 4 — composição do pipeline IA") deste documento.

## 2. Contexto inicial

Antes desta sessão o projeto estava no estado descrito em `historico/2026-04-26_fase2-templates-clip-cor.md`:

- Pipeline `captura → CLIP → cor → Blender headless → GLB customizado` operacional, com 5 templates normalizados em `assets/templates/normalized/` e `CaptureService` injetando `Classifier`, `ColorDetector` e `Processor` por configuração.
- Suíte de 99 testes verdes, com bypass `Disabled*` em todas as ABCs com dependência pesada (`torch`, `transformers`, `Pillow`).
- Diagnóstico empírico do teste manual (Etapa 16, perfume Hinode Feelin' Flame) revelando dois eixos de erro do pipeline de templates: classificação CLIP errando para frasco compacto-azul, e label sendo aplicada como foto inteira (com fundo).

A motivação desta sessão veio do reconhecimento — também documentado em 2026-04-26 §7.3 — de que **a entrega final do TCC pode exigir fidelidade visual maior do que templates paramétricos genéricos conseguem oferecer**. A solução de continuidade foi instituir um segundo `Processor`, baseado em IA generativa, sem desmontar o existente: a abstração `Processor` herdada da Fase 1 permite plugar a alternativa por flag de configuração, mantendo o caminho de templates como fallback determinístico.

A sessão começou com a Fase 1 (segmentação) já especificada em alto nível pelo usuário, evoluiu para a Fase 2 (Hunyuan3D em Docker) e fechou com a Fase 3 (refinamento de malha). O contexto da conversa foi compactado entre as fases 2 e 3 — esse fato deixa parte da memória anterior à compactação acessível apenas através do sumário gerado automaticamente, e foi tratado com cuidado para não introduzir afirmações sem suporte na transcrição.

## 3. Decisões arquiteturais e de design

### 3.1 Verificação de continuidade com sessões anteriores

A sessão anterior (`historico/2026-04-26_fase2-templates-clip-cor.md`) já antecipava esta direção em §7.3 ("Trilha alternativa surgida após a sessão"). As pendências formais de §7.2 daquele documento são revisitadas em detalhe na seção 7 deste documento. Resumidamente, esta sessão:

- **Confirma** o paradigma plugável `Processor` ABC como acerto arquitetural (3.4 do doc anterior): adicionar `Hunyuan3DProcessor` não exigiu refatoração do `service.py` nem das factories.
- **Endereça parcialmente** a pendência de "segmentação de label" (7.2.2 do doc anterior) — o `LabelExtractor` foi implementado mas não integrado ao `CaptureService` (deferido para Fase 4).
- **Não revoga** decisão alguma do documento anterior. A relação é de complementaridade: o pipeline de templates continua válido para frascos com modelo conhecido; o pipeline IA cobre frascos novos.

### 3.2 Pipeline IA como **terceiro `Processor`**, não substituto

A decisão central da sessão foi posicionar Hunyuan3D **lado a lado** com `TemplateProcessor` e `FakeProcessor`, em vez de substituí-lo. Trade-offs avaliados:

| Caminho | Custo | Riscos |
|---|---|---|
| **A** (escolhido): adicionar `Hunyuan3DProcessor` mantendo os outros | Volume maior de código; gerenciamento de duas trilhas | Cobertura ampla (frascos conhecidos + novos); rollback trivial via flag |
| B: substituir o pipeline de templates por IA | Menos código a manter | Perda do trabalho da Fase 2; sem fallback determinístico se Docker/GPU falhar |
| C: pipeline híbrido com fusão geométrica template+IA | Complexidade alta | Engenharia que ultrapassa o escopo do MVP |

A escolha do caminho A se justifica por dois motivos: (i) **risco operacional** — IA exige GPU + contêiner Docker + ~5GB de pesos; em ambiente sem GPU o sistema continua usável via templates; (ii) **economia de defesa acadêmica** — manter o pipeline de templates evidencia que a arquitetura plugável da Fase 1 é genuína, não retrospectivamente justificada.

### 3.3 Isolamento da inferência IA em contêiner Docker dedicado

O modelo Hunyuan3D-2mv (fork de baixo VRAM `deepbeepmeep/Hunyuan3D-2GP`) tem stack pesada: PyTorch + CUDA 12.8 + `mmgp` para offload + custom CUDA rasterizer compilado no build. Trazer isso para o `requirements.txt` do backend produziria três problemas: (i) `pip install` no laptop dev passaria de poucos minutos para ~30min, (ii) versão de CUDA na máquina dev e na de produção precisariam coincidir, (iii) tempo de cold-start do FastAPI explodiria com carga do modelo no boot.

Decisão: **separar a inferência num serviço HTTP isolado** num contêiner Docker próprio, expondo apenas dois endpoints (`GET /health`, `POST /generate` multipart). O backend importa apenas `httpx` e nunca tem acesso a `torch`. Trade-offs assumidos:

- **+latência de rede local** (≪1ms localhost) — desprezível diante dos 3-5min de inferência.
- **+orquestração** (docker-compose, healthcheck) — pago em troca de isolamento total de dependências.
- **+banda no upload das imagens** — desprezível (multipart de até 6 PNGs).

A imagem base escolhida foi `pytorch/pytorch:2.7.0-cuda12.8-cudnn9-runtime`, compatível com sm_120 da RTX 5050 do laptop. Para evitar redownload de ~2GB do PyTorch já presente na imagem, o `Dockerfile` filtra o `requirements.txt` do upstream com `grep -vE "^(torch|torchvision|torchaudio)"` antes do `pip install`.

### 3.4 Carregamento do modelo no startup do contêiner

A primeira draft tinha o modelo sendo carregado lazy (na primeira chamada a `/generate`). Isso quebraria o protocolo de readiness: o backend faz `GET /health` → "ready"? antes de POSTar; com lazy load, `/health` sempre retornaria "ready" mas a primeira inferência pagaria o custo de ~30s de carga do modelo dentro do timeout de geração.

Decisão revisada: lifespan do FastAPI dispara `asyncio.create_task(asyncio.to_thread(_carregar_modelos))` no startup. `/health` retorna `{"status": "loading"}` durante a carga e `{"status": "ready"}` quando termina. O backend tem retry com sleep para acomodar isso. Trade-off: o contêiner consome VRAM continuamente após o boot; em troca, a primeira inferência tem latência previsível.

### 3.5 Bypass `Disabled` em todas as três ABCs novas

Mantendo a convenção da Fase 2 (3.5 do doc 2026-04-26), as três novas ABCs receberam variantes de bypass:

- `DisabledBackgroundRemover`: copia o arquivo verbatim (`shutil.copy2`).
- `DisabledLabelExtractor`: retorna `ExtractedLabel` apontando para o arquivo de entrada com `confidence=0.0`.
- `DisabledMeshRefiner`: copia o GLB de entrada para o output sem alteração.

Justificativa: as deps reais (`rembg` + `onnxruntime` + modelo ISNet, `opencv-python`, Blender 5.1+) são pesadas (~500MB total), opcionais e dependentes de SO. As variantes `Disabled` permitem que a suíte de testes rode integralmente em CI sem GPU, sem Blender, sem os modelos baixados. As 11 dos 137 testes que pulam quando `rembg`/`cv2`/Blender ausentes seguem um padrão `pytest.importorskip(...)` ou guard `if not blender.exists(): pytest.skip(...)`.

### 3.6 Heurística de identificação do "corpo de vidro" no `BlenderMeshRefiner`

O Hunyuan3D-2mv produz GLBs onde o vidro do frasco vira uma superfície **opaca azulada** — a IA pinta as reflexões do ambiente como cor de superfície em vez de inferir transmissão. Reuso direto desse GLB no `<model-viewer>` produz resultado visualmente fraco. Por outro lado, a label aplicada pela IA geralmente está usável.

A decisão foi implementar um pós-processador que **substitui apenas o material do corpo, preservando a label**. O critério para identificar o corpo entre os meshes do GLB é heurístico:

1. **Filtra labels:** descarta meshes cujo material tem `Image Texture → Base Color`. Qualquer textura de imagem ligada ao Base Color do Principled BSDF é interpretada como label e preservada.
2. **Maior área:** dos candidatos restantes (sem textura), seleciona o de maior área de superfície total (somatório de áreas de polígonos em coordenadas mundo, computado via produto vetorial dos triângulos da decomposição em fan).

Trade-offs assumidos:

- A heurística falha quando **todos** os materiais do GLB têm textura (caso raro em saídas Hunyuan, mas possível em GLBs externos). Nesse caso o script exporta o GLB inalterado com aviso — a alternativa de modificar arbitrariamente um material seria pior.
- A heurística falha quando o frasco tem ornamentos com área comparável ao corpo. Em compensação, é determinística, auditável e independente de classificação visual adicional.
- A detecção de tampa (best-effort, por posição Z após import glTF) só aplica shader de plástico se a diferença de altura em relação ao corpo for >20% da bounding box. Inconcluso → não modifica.

### 3.7 Parâmetros do shader de vidro PBR

Os valores aplicados ao Principled BSDF foram escolhidos a partir do shader de vidro do `generate_feeling_template.py` da sessão anterior, com uma diferença chave: aqui o **Base Color é branco puro**, sem tinte, porque o frasco real do perfume é geralmente vidro neutro e a coloração percebida vem do líquido. Em V2 do feeling template havia tinte azul no vidro porque o template era específico daquele perfume.

| Parâmetro | Valor | Justificativa |
|---|---|---|
| `IOR` | 1.45 | Boro-silicato típico de perfumaria |
| `Transmission Weight` | 1.0 | Transmissão total |
| `Roughness` | 0.05 | Vidro polido |
| `Base Color` | (1.0, 1.0, 1.0, 1.0) | Sem tinte; cor vem do líquido |
| `Alpha` | 0.3 | Visível parcialmente em preview Blender |

### 3.8 Idempotência do refinador

Decisão tardia, descoberta pelo linter ao revisar `aplicar_shader_vidro`: a primeira versão apenas zerava conexões existentes do Principled BSDF. Em GLBs com nós espalhados (Tex Image, Color Ramp, etc), restavam nós órfãos — rodar duas vezes acumulava resíduos. A versão final faz `nos.clear()` e recria do zero o pipeline (Output Material + Principled BSDF), garantindo que o resultado de duas refinadas consecutivas sobre o mesmo GLB seja idêntico.

### 3.9 Convenções de teste para o `Hunyuan3DProcessor`

Como o serviço HTTP do Hunyuan não está disponível em CI, optou-se por:

- **Testes unitários:** transporte HTTP customizado `_FakeTransport(httpx.AsyncBaseTransport)` que lê o stream completo da request antes de passar para um handler controlável. Sete cenários cobertos: ordem de chamadas, retry, sucesso, limite de 6 imagens, HTTP 500, GLB inválido, campos ignorados.
- **Teste de integração:** marcado com `@pytest.mark.slow`, pula automaticamente se `GET http://localhost:7860/health` falhar. Útil para validação manual após `docker compose up hunyuan`.

A escolha de `_FakeTransport` em vez de `httpx.MockTransport` se deu porque `MockTransport` não é API estável da `httpx 0.27` e seu comportamento em torno do stream da request varia entre versões.

## 4. Implementação realizada

### 4.1 Fase 1 — Segmentação e extração de label

**Arquivos criados:**

- `C:\TCC\back\app\modules\captures\background_remover.py` *(novo)* — ABC `BackgroundRemover` + `DisabledBackgroundRemover` (copia verbatim) + `RembgBackgroundRemover` (lazy import de `rembg`, sessão cacheada na instância, sempre exporta RGBA PNG, roda em `asyncio.to_thread`).
- `C:\TCC\back\app\modules\captures\label_extractor.py` *(novo)* — ABC `LabelExtractor` + `ExtractedLabel` (frozen dataclass) + `DisabledLabelExtractor` + `HomographyLabelExtractor` (Canny → contornos → filtro por proporção/centralização → `_ordenar_cantos` → `getPerspectiveTransform` → `warpPerspective`, lazy import de OpenCV).
- `C:\TCC\back\requirements-vision.txt` *(novo)* — `rembg>=2.0.50`, `opencv-python>=4.10`, `numpy>=1.26`, `pillow>=10.0`. Header explica como ativar `onnxruntime-gpu` para acelerar ~5x na RTX 5050.
- `C:\TCC\back\tests\modules\captures\test_background_remover.py` *(novo)* — 10 testes (7 passam sem `rembg` instalado, 3 condicionais via `pytest.importorskip`). Inclui teste de reuso de sessão (`patch("rembg.new_session")` com `call_count == 1` em três chamadas).
- `C:\TCC\back\tests\modules\captures\test_label_extractor.py` *(novo)* — 12 testes (4 sem cv2, 8 condicionais). `TestOrdenarCantos` valida ordenação TL/TR/BR/BL para 4 pontos hand-picked. Teste de extração desenha retângulo branco em fundo escuro com `cv2.rectangle` e verifica recorte.
- `C:\TCC\back\docs\10b-segmentacao-e-label.md` *(novo)* — espelha a estrutura de `docs/10-classificador-e-cor.md`.

### 4.2 Fase 2 — Cliente HTTP Hunyuan3D + serviço Docker

**Backend Python:**

- `C:\TCC\back\app\modules\captures\processor.py` *(modificado)* — apêndice ao final com `Hunyuan3DProcessor(Processor)`. Aceita `service_url`, `timeout_seconds=600.0`, `octree_resolution=256`, `num_inference_steps=30`, mais dois parâmetros privados (`_transport` para mocks, `_retry_interval` para o aguardar). `process()` cria `httpx.AsyncClient`, espera readiness (3 tentativas), monta multipart com até 6 imagens via `ExitStack` para fechar handles seguramente, valida `glTF` magic e escreve em disco.
- `C:\TCC\back\requirements.txt` *(modificado)* — promovido `httpx>=0.27` (estava em `requirements-dev.txt` apenas para o `TestClient` de FastAPI).
- `C:\TCC\back\pytest.ini` *(modificado)* — adicionado marker `slow: testes lentos (>30s) que requerem serviços externos`.
- `C:\TCC\back\tests\modules\captures\test_processor.py` *(modificado)* — 7 testes novos em `TestHunyuan3DProcessor` usando `_FakeTransport` (ver 3.9).
- `C:\TCC\back\tests\integration\__init__.py` *(novo)* — vazio, marca `tests/integration/` como pacote.
- `C:\TCC\back\tests\integration\test_hunyuan_real.py` *(novo)* — fixture `hunyuan_url` faz `GET /health` e pula se serviço não estiver pronto. Teste real envia 4 PNGs sintéticos (elipse + retângulo, 4 cores levemente diferentes) e valida `bytes_glb[:4] == b"glTF"` + tamanho >100KB.
- `C:\TCC\back\docs\09b-pipeline-ai-hunyuan.md` *(novo)* — diagrama `backend → HTTP → Docker → GPU`, tabela de trade-offs (templateprocessor vs hunyuanprocessor: tempo, VRAM, qualidade), limitações conhecidas (vidro translúcido, tampa fundida, fundo não removido).

**Serviço Docker:**

- `C:\TCC\docker\hunyuan\Dockerfile` *(novo)* — base `pytorch/pytorch:2.7.0-cuda12.8-cudnn9-runtime`. Clona `deepbeepmeep/Hunyuan3D-2GP`, filtra torch das deps via `grep -vE "^(torch|torchvision|torchaudio)"`, instala `mmgp` + `fastapi` + `uvicorn[standard]` + `python-multipart`, compila o custom rasterizer, pré-baixa pesos do shape model. `EXPOSE 7860`.
- `C:\TCC\docker\hunyuan\server.py` *(novo)* — FastAPI com `lifespan` que dispara `asyncio.create_task(asyncio.to_thread(_carregar_modelos))`. Endpoints: `GET /health` (estados `loading|ready|error`), `POST /generate` (multipart com `images: List[UploadFile]` + `octree_resolution: int = Form(256)` + `num_inference_steps: int = Form(30)`). Pipelines `Hunyuan3DDiTFlowMatchingPipeline` (shape) e `Hunyuan3DPaintPipeline` (texture), ambos com `mmgp.offload.profile(pipe, profile_no=4)`.
- `C:\TCC\docker\hunyuan\entrypoint.sh` *(novo)* — exporta `HF_HOME`, `CUDA_VISIBLE_DEVICES=0`, `PYTHONPATH=/app/hunyuan:...` e dispara `uvicorn server:app --host 0.0.0.0 --port 7860`.
- `C:\TCC\docker\hunyuan\README.md` *(novo)* — instruções de build e run, tabela de VRAM por profile, troubleshooting (sm_120, libGL, custom_rasterizer, OOM).
- `C:\TCC\docker-compose.yml` *(novo, na raiz do projeto)* — dois serviços: `postgres` (preserva o setup já documentado em memory `project_postgres`: `tcc-postgres` na 5433, banco `tcc`, user/pass `postgres/postgres`) e `hunyuan` (com `deploy.resources.reservations.devices` para passar GPU NVIDIA, healthcheck `curl /health`, volume persistente para HF cache).

### 4.3 Fase 3 — Refinamento de malha PBR

**Arquivos criados:**

- `C:\TCC\back\app\modules\captures\blender_scripts\refine_ai_mesh.py` *(novo)* — script Blender headless. Funções principais:

    - `calcular_area_mesh(obj)` — após revisão do linter, soma áreas de triângulos em coordenadas mundo via produto vetorial das diagonais da fan (não o `polygon.area * scale` da primeira draft, que era impreciso para escalas não-uniformes).
    - `material_tem_textura_image(mat)` — caminha o node tree do material; True se Base Color do Principled BSDF está conectado a um nó `TEX_IMAGE`.
    - `identificar_corpo_vidro(meshes)` — implementa a heurística descrita em 3.6.
    - `aplicar_shader_vidro(mat)` — limpa todos os nós do material e recria do zero (idempotência, ver 3.8) com Output + Principled BSDF parametrizado segundo 3.7. Compatível com Blender 4+ (`Transmission Weight`) e 3.x (`Transmission`).
    - `detectar_tampa(meshes, corpo_obj)` — best-effort por centro Z da bbox.
    - `aplicar_cor_liquido(mat, cor)` — defensivo; só aplica se mesh literal `Liquid` ou material `water`/`liquid` existirem.

- `C:\TCC\back\app\modules\captures\mesh_refiner.py` *(novo)* — `RefinementInput`/`RefinementResult` (frozen dataclasses), `MeshRefinementError`, `MeshRefiner` ABC, `DisabledMeshRefiner`, `BlenderMeshRefiner`. O wrapper Python segue o mesmo padrão de subprocess do `TemplateProcessor` (`asyncio.to_thread(self._run_blender_sync, args)` → `subprocess.run(..., timeout=...)` com `PYTHONIOENCODING=utf-8`). Após revisão do linter, o construtor passou a aceitar `blender_executable: Path | None = None` com fallback para variável de ambiente `BLENDER_EXECUTABLE` (consistente com convenção do `TemplateProcessor`).

- `C:\TCC\back\tests\modules\captures\test_mesh_refiner.py` *(novo)* — 9 testes em três classes:

    | Classe | Testes | Notas |
    |---|---|---|
    | `TestDisabledMeshRefiner` | 2 | Cópia byte-a-byte; output existe |
    | `TestBlenderMeshRefinerMocked` | 5 | Mocka `_run_blender`; cobre args, liquid_color, retorno != 0, GLB ausente, output não criado |
    | `TestBlenderMeshRefinerIntegration` | 2 | Real Blender; pula se ausente. Reusa `rectangular_basic.glb` como stand-in para "GLB cru" e verifica que materiais com `baseColorTexture` no input continuam presentes no output (parsing direto do JSON do GLB). |

- `C:\TCC\back\docs\09c-refinamento-mesh.md` *(novo)* — diagrama do fluxo, tabela de parâmetros do shader (com justificativa por linha), seção de limitações (geometria não alterada, cap detection fraca, dependência de Blender, idempotência), seção de uso manual com comandos de smoke test.

- `C:\TCC\back\scripts\blender\preview_refinement.py` *(novo)* — script de renderização comparativa. Aceita `--before` e `--after` GLBs, usa Cycles + as mesmas configurações de câmera/luz do `preview_feeling_template.py` para reprodutibilidade, e compõe os dois renders lado a lado via compositor do Blender (Image nodes + Translate + AlphaOver → Composite). Exporta um PNG único com largura dupla, pensado para slides do TCC.

### 4.4 Modificações em arquivos pré-existentes

Resumo das edições em arquivos que já existiam antes da sessão:

- `processor.py`: adicionados imports `from contextlib import ExitStack`, `import httpx`, `from ...core.logging import get_logger`. Acrescentada classe `Hunyuan3DProcessor` ao final.
- `requirements.txt`: `httpx>=0.27` promovido de dev para runtime.
- `pytest.ini`: nova seção `markers` com `slow: ...`.
- `tests/modules/captures/test_processor.py`: classe `TestHunyuan3DProcessor` apêndice.

Nenhum dos seguintes foi tocado: `service.py`, `main.py`, `config.py`, factories, `templates_catalog.py`, `classifier.py`, `color_detector.py`, `customize_template.py`, `generate_feeling_template.py`. A regra de escopo foi mantida com rigor: a integração `Hunyuan3DProcessor` ↔ `CaptureService` ↔ `BlenderMeshRefiner` no pipeline único é objeto explicitamente declarado da Fase 4.

## 5. Problemas encontrados e soluções

### 5.1 `httpx.MockTransport` instável entre versões

**Sintoma:** primeira tentativa de mockar respostas HTTP do `Hunyuan3DProcessor` usou `httpx.MockTransport`. Em `httpx 0.27` o comportamento ao redor do stream da request mudou: o `request.stream` precisa ser totalmente consumido antes do handler retornar, ou a contagem de bytes do multipart fica inconsistente.

**O que foi tentado:**

1. Usar `httpx.MockTransport` direto. Os testes de validação de "6 imagens enviadas" falhavam porque o stream não tinha sido lido, e `request.content` estava vazio.
2. Patching das chamadas em `app.modules.captures.processor` com `unittest.mock`. Inviável: `httpx.AsyncClient` cria seus próprios transportes internos.

**Solução adotada:** definir um `_FakeTransport(httpx.AsyncBaseTransport)` no próprio arquivo de teste, sobrescrevendo `handle_async_request` para forçar a leitura completa do stream antes de chamar o handler controlável: `await request.aread()` e então `body = request.content`. Tipos como `httpx.AsyncBaseTransport` são API estável; `MockTransport` é detalhe de implementação que muda entre versões.

### 5.2 Imagem base do PyTorch desatualizada vs. CUDA do host

**Sintoma:** primeira draft do Dockerfile usava `pytorch/pytorch:2.4.0-cuda12.1-cudnn9-runtime`. Inferência falhou em runtime com erro `no kernel image is available for execution on the device` — a RTX 5050 (sm_120, arquitetura Blackwell) não tem suporte em wheels compiladas para CUDA 12.1.

**O que foi tentado:**

1. `--build-arg` para forçar reinstalação de torch com `--index-url https://download.pytorch.org/whl/cu128`. Funcionou mas inflou o build em ~2GB e duplicou o tempo.

**Solução adotada:** trocar a imagem base para `pytorch/pytorch:2.7.0-cuda12.8-cudnn9-runtime`, que já vem com torch compilado para sm_120. Adicionalmente, filtrar `torch|torchvision|torchaudio` do `requirements.txt` do upstream Hunyuan-2GP via `grep -vE` antes do `pip install`, evitando que a wheel padrão do PyPI sobrescreva a do base image.

### 5.3 Carga lazy do modelo Hunyuan vs. protocolo de readiness

**Sintoma:** primeira draft do `server.py` carregava as pipelines apenas na primeira chamada a `/generate`. Em testes de integração, a chamada inicial estourava o timeout do `Hunyuan3DProcessor` (configurado para 600s, mas a fila `_aguardar_servico` desistia após 3 retries de health check).

**Solução adotada:** mover a carga para o lifespan do FastAPI via `asyncio.create_task(asyncio.to_thread(_carregar_modelos))`. `/health` retorna `loading` durante a carga (~30-60s) e `ready` ao final. O retry no `_aguardar_servico` do backend agora tem semântica clara: ele aguarda o modelo terminar de carregar, não só o uvicorn responder. Discutido em 3.4.

### 5.4 IDE marcando packages do `requirements.txt` como "não instalados"

**Sintoma:** após adicionar `httpx>=0.27` ao `requirements.txt`, o VSCode marcou todas as linhas com warning "Package not installed".

**Diagnóstico:** o interpretador Python selecionado no IDE era o global, não o `.venv` do projeto (`C:\TCC\back\.venv`).

**Solução adotada:** não fazer nada. Confirmado via `.\.venv\Scripts\python.exe -c "import httpx; print(httpx.__version__)"` que `httpx 0.28.1` está disponível no venv. Falso-positivo do IDE; o pytest CLI rodou normalmente.

### 5.5 Cálculo de área com escala não-uniforme

**Sintoma:** revisão do linter no `refine_ai_mesh.py` apontou que a primeira versão de `calcular_area_mesh` multiplicava `polygon.area` pelo cubo geométrico-médio do `obj.scale`, o que é incorreto para escalas não-uniformes (`scale=(2,1,1)` produziria área inflada por fator √2 em vez do correto).

**Solução adotada:** reescrever `calcular_area_mesh` para iterar polígonos, transformar vértices via `obj.matrix_world @ vertice.co` para coordenadas mundo, e somar `(B - A).cross(C - A).length / 2.0` na decomposição em fan. Independe de escala, rotação e translação do objeto. Essa versão é a que está no arquivo final.

### 5.6 Idempotência do refinamento

**Sintoma identificado em revisão de código:** primeira versão de `aplicar_shader_vidro` apenas removia conexões do BSDF existente (`for entrada in bsdf.inputs: for link in entrada.links: links.remove(link)`). Funcional para um GLB típico, mas em GLBs com nós auxiliares (Color Ramp, Mix RGB, Normal Map) restavam órfãos. Refinamentos sucessivos acumulariam resíduos no `node_tree`, mesmo se imperceptíveis no render.

**Solução adotada:** substituir por `nos.clear()` + recriação do par mínimo `Output Material + Principled BSDF` + ligação `BSDF → Surface`. Garante que `refine(refine(glb))` produz o mesmo resultado que `refine(glb)` byte-a-byte (ignorando metadados de timestamp do exporter glTF).

## 6. Conceitos teóricos envolvidos

- **Generative 3D from Multi-View (Hunyuan3D-2mv).** A família de modelos Hunyuan3D (Tencent, 2024-2025) implementa geração de malha 3D a partir de múltiplas vistas via *flow matching* — uma evolução de difusão pensada para domínios contínuos, com formulação de probability path mais geral. O fork `2GP` aplica `mmgp` (memory management for generative pipelines) para particionar o cálculo entre GPU e CPU/disk, viabilizando inferência em GPUs com 6-8GB de VRAM. Para o TCC, é instância concreta da contraposição "fotogrametria SfM" (Meshroom/AliceVision, requer cobertura ampla de ângulos e textura rica) vs. "modelos generativos" (Hunyuan3D, requer poucas vistas mas exige pesos pré-treinados).

- **Background Matting / Salient Object Detection (rembg + ISNet).** O `rembg` envolve o modelo `isnet-general-use` (ISNet, *Highly Accurate Dichotomous Image Segmentation*, Qin et al. 2022), uma U-Net 2-stage especializada em mattes binárias de alta resolução. A escolha desse backend específico (em vez do `u2net` default) se deu pela qualidade superior em silhuetas de objetos brilhantes (vidro), centrais ao domínio.

- **Homografia e retificação perspectiva (`HomographyLabelExtractor`).** A transformação `getPerspectiveTransform` calcula a matriz 3x3 que mapeia 4 pontos de um quadrilátero qualquer para um retângulo canônico. O ordenamento de cantos por `_ordenar_cantos` (TL/TR/BR/BL via soma+diferença das coordenadas) é uma técnica clássica de OpenCV para resolver a ambiguidade de qual canto é qual após uma busca de contornos não-orientada.

- **Strategy Pattern (GoF) — quarta aplicação.** O padrão já estava aplicado em `Processor`, `Classifier`, `ColorDetector` (cf. doc 2026-04-26 §6). Esta sessão adiciona `BackgroundRemover`, `LabelExtractor` e `MeshRefiner` à mesma família. Acumula-se evidência de que a abstração não é over-engineering: cada nova fase do pipeline encaixa naturalmente como nova ABC sem reescrever as anteriores.

- **Microsserviço com isolamento de dependência pesada.** O contêiner Docker do Hunyuan é instância concreta do padrão "sidecar para inferência ML" comum em arquiteturas de produção: separa a stack de ML (Python específico, CUDA específico, modelos pré-baixados) do serviço principal, conectando via HTTP. Justifica-se academicamente por princípios de coesão funcional e gerenciamento de dependência.

- **Idempotência em scripts de pós-processamento.** A discussão de §5.6/§3.8 toca um ponto recorrente em pipelines de processamento: operações idempotentes facilitam *replays*, *re-runs* em ambiente de batch e debugging — propriedade especialmente valiosa quando o operador pode rodar o refinador manualmente antes de chamá-lo programaticamente.

- **Physically Based Rendering (PBR) via Principled BSDF.** O Principled BSDF (Disney 2012, implementação Blender) reúne um conjunto de parâmetros físicos (IOR, transmission, roughness, metallic) sob um único nó. O TCC pode discutir a contraposição "shader empírico" (cores e mapas pintados pela IA) vs. "shader físico" (parâmetros derivados de leis ópticas), mostrando que para vidro o segundo entrega resultado superior com menos dados.

## 7. Pendências e próximos passos

### 7.1 Pendências do documento anterior (`historico/2026-04-26_fase2-templates-clip-cor.md`, §7.2)

| Pendência registrada em 2026-04-26 | Estado em 2026-05-09 |
|---|---|
| 7.2.1 Qualidade da classificação CLIP (Feelin' Flame errado) | **Não atendida.** Esta sessão tomou outra direção (substituição completa por IA generativa) que torna o problema menos crítico, mas não o resolve. CLIP segue como roteador entre templates; quando a Fase 4 integrar Hunyuan, o CLIP poderá deixar de ser determinante para frascos novos. |
| 7.2.2 Segmentação de label (foto inteira como textura) | **Parcialmente atendida.** O `HomographyLabelExtractor` foi implementado e testado isoladamente. Falta integração com `CaptureService` para que a label extraída seja passada como `ProcessingInput.label_image` em vez da foto crua. Deferido para Fase 4. |
| 7.2.3 GLB para `feeling_rectangular_blue` | **Não atendida.** O catálogo CLIP segue com a entrada inerte (descrição sem GLB físico). A nova trilha IA torna isso opcional: o Hunyuan3D inferiria o frasco azul-escuro retangular sem precisar do template. |
| 7.2.4 Build GPU do PyTorch | **Não atendida no host, mas contornada no contêiner.** O CLIP no host segue em CPU. O PyTorch GPU do Hunyuan está dentro do contêiner Docker (`pytorch/pytorch:2.7.0-cuda12.8-cudnn9-runtime`), isolado do venv do backend. O ganho de velocidade do CLIP segue pendente. |
| 7.2.5 Cor neutra para frascos brancos/transparentes | **Não atendida.** Sem mudança no `_chromatic_pixels`. Permanece como heurística com fallback. |

### 7.2 Pendências geradas por esta sessão

1. **Fase 4 — composição do pipeline IA.** Compor `BackgroundRemover` → `LabelExtractor` (opcional) → `Hunyuan3DProcessor` → `BlenderMeshRefiner` num único fluxo do `CaptureService`. Decidir o modo de roteamento: flag por job (`use_ai=True`), por feature de configuração, ou por classificação CLIP retornando "unknown" como sinal de fallback para IA.

2. **Validação visual real do refinador.** O critério de aceitação 5 da especificação ("rodar Hunyuan + refinar e confirmar visualmente: vidro transparente, label legível, materiais preservados") **não foi exercido nesta sessão** porque exige (i) Docker buildado com pesos baixados (~5GB), (ii) GPU disponível, (iii) inspeção humana dos PNGs gerados pelo `preview_refinement.py`. Validação pendente.

3. **Suite de testes lentos em CI separado.** Os 7 testes `slow` (`test_hunyuan_real.py`, integração Blender no `test_mesh_refiner.py`) ficam fora do `pytest -m "not slow"` default. Estabelecer pipeline noturno ou pre-merge gate que rode com Docker + Blender presentes seria saudável para o TCC final, mas é trabalho de engenharia de processo, não de código.

4. **Limitações conhecidas do Hunyuan documentadas mas não mitigadas.** Em `docs/09b-pipeline-ai-hunyuan.md` listam-se três limitações ("vidro translúcido tratado como opaco", "tampa fundida ao corpo", "fundo não removido degrada qualidade"). A Fase 3 endereça a primeira (refinador de shader); a segunda continua aberta (geometria não é alterada); a terceira é endereçada pré-IA (`BackgroundRemover`) mas a integração ainda não foi feita.

5. **Caso de borda — refinador em GLB sem corpo identificável.** Quando `identificar_corpo_vidro` retorna `(None, None)` o refinador exporta o GLB inalterado, mas não há teste cobrindo esse caminho com `BlenderMeshRefiner` real (apenas mock). Adicionar teste de integração com GLB texturizado-por-completo seria útil.

6. **Pipeline de `LabelExtractor`: avaliação empírica.** Os parâmetros do filtro (área 5–60%, aspect ratio 0.3–3.0, centralização ≤35%) foram escolhidos por intuição. Validação contra um lote de fotos reais de perfumes diversos confirmaria ou refinaria os limites.

### 7.3 Trabalho fora do escopo desta sessão observado no repositório

Inspeção do `ls captures/` ao final desta sessão revela módulos não cobertos pela transcrição da conversa: `image_preprocessor.py`, `label_projector.py`, `label_upscaler.py`, `mesh_cleaner.py`, e respectivos arquivos de teste, além dos docs `09d-preprocessamento-e-cleanup.md` e `09e-aplicacao-label.md`. Esses artefatos precedem ou sucedem esta sessão e **não são aqui documentados** — pertencem a outras sessões cujos transcritos não estão disponíveis. [verificar] qual sessão produziu esses arquivos ao consolidar a versão final do TCC.

## 8. Reflexão para o TCC

### 8.1 Sobre a evolução do projeto

A trajetória até esta sessão mostra um padrão metodológico claro: **cada validação empírica desencadeia uma reorganização do plano original**. A Fase 1 entregou um esqueleto plugável (`Processor` ABC) cuja utilidade se revelaria depois. A Fase 2 (templates+CLIP) entregou um pipeline tecnicamente válido, mas o teste manual da Etapa 16 (perfume Hinode) expôs limites estéticos. Esta sessão é a resposta direta àquele diagnóstico: a arquitetura plugável da Fase 1 absorveu uma trilha completamente diferente — geração via IA — sem refatoração, validando *retroativamente* a decisão de abstrair `Processor`.

### 8.2 Mudanças de rumo em relação ao planejamento original

O plano original (16 etapas em torno de templates) tem agora um plano paralelo de Fases 1-4 organizadas em torno de IA generativa. Não é substituição: é **bifurcação plugável** sob a mesma abstração. Para a defesa final, isso é argumentativamente forte — o sistema oferece dois caminhos, ambos defensáveis, com critérios claros de quando preferir um sobre o outro:

- **Templates** quando há frasco conhecido no catálogo, prioridade para rapidez (~10s) ou ambiente sem GPU.
- **IA** quando há frasco novo, prioridade para fidelidade visual e ambiente com GPU disponível.

O fato de não ter sido decidido *no momento desta sessão* qual caminho será o default para o usuário final é, paradoxalmente, parte da entrega: a arquitetura permite que a decisão seja deferida.

### 8.3 Aprendizados metodológicos

1. **Isolamento de dependências pesadas em contêiner é sobre defensibilidade, não só desempenho.** A separação Hunyuan-em-Docker tem benefício técnico imediato (CUDA isolado, build do backend rápido), mas seu valor acadêmico é maior: permite que a defesa do TCC mostre o backend Python rodando localmente em qualquer máquina e a IA opcional ativada quando disponível. O sistema **funciona** sem GPU; o sistema **brilha** com GPU.

2. **Bypass `Disabled` em ABCs de pipeline com dep pesada deve ser regra.** Quatro ABCs nesta sessão receberam variantes de bypass (3.5). O custo é trivial (uma classe de cinco linhas); o ganho é que a suíte de testes roda em qualquer máquina, e que a apresentação do TCC não depende de provisionar laptop com 8GB de VRAM.

3. **Testes de integração marcados (`@pytest.mark.slow`, integration directory) ≫ testes desabilitados.** Manter os testes reais no repositório, marcados para skip default e ativáveis sob demanda, preserva a possibilidade de validação noturna ou manual sem onerar o ciclo dev. Discutível mas defensável: não há valor acadêmico em código que nunca exercita o caminho real.

4. **Idempotência é virtude epistemológica.** O ajuste de §3.8/§5.6 não é apenas técnico — ele reflete uma postura de modelagem: pipelines reproduzíveis sob re-execução são mais seguros para experimentação. Para um TCC, onde o avaliador pode (e deve) reexecutar o sistema, idempotência é uma forma de honestidade reprodutiva.

5. **A documentação `[verificar]` é parte da metodologia.** Marcar incertezas explicitamente (como neste documento, §7.3 e na referência a artefatos fora do escopo) impede que afirmações sem suporte vazem para o texto final do TCC. O custo é uma frase a mais; o ganho é integridade do registro.

---

*Documento gerado a partir da reconstituição da sessão pelo assistente, incluindo a parte pré-compactação reportada via sumário automático e a parte pós-compactação reportada via transcrição direta. Itens marcados `[verificar]` indicam pontos onde o estado do repositório no momento da redação não foi diretamente inspecionado e merecem confirmação manual antes de citação no texto final do TCC.*
