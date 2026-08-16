# 09b — Pipeline IA: Hunyuan3D-2mv

> **O que você vai aprender neste doc**
> - Por que a geração 3D vive em um **container Docker separado** (com GPU) e não no backend.
> - Como o `Hunyuan3DProcessor` (cliente HTTP) conversa com esse serviço via `POST /generate`.
> - Os parâmetros de inferência (`octree_resolution`, `num_inference_steps`, ...) e por que esses valores.
> - As limitações do modelo (vidro, tampa, texto da label) e como o pós-processamento as mitiga.
>
> **Pré-requisitos:** [09f - Pipeline integrado](09f-pipeline-integrado.md) (onde este stage encaixa).

Implementação da etapa de **geração** dentro do `IntegratedPipeline`. O `Hunyuan3DProcessor` é o cliente HTTP que conversa com o contêiner Docker dedicado ao modelo [Hunyuan3D-2mv](https://github.com/Tencent/Hunyuan3D-2) (fork low-VRAM por deepbeepmeep). Recebe 1–6 fotos pré-processadas e segmentadas e devolve um GLB com geometria + textura PBR.

Esse processor **não** é mais usado como Strategy raiz solta — ele é um *stage* dentro do `IntegratedPipeline` (ver [09f](09f-pipeline-integrado.md)). Continua sendo possível instanciá-lo direto nos smokes para depurar a inferência isoladamente.

## Por que Hunyuan3D-2mv

- O antigo `TemplateProcessor` gerava modelos de alta qualidade para frascos conhecidos, mas exigia um GLB normalizado para cada formato — não generalizava. Foi removido em 2026-08.
- Hunyuan3D-2mv aceita até 6 vistas, infere geometria + textura PBR sem template, e funciona em GPUs domésticas (testado em RTX 5050 8GB com `mmgp profile 4`).
- Para perfumes recorrentes (mesmo frasco fotografado de novo), o **cache de similaridade CLIP** evita pagar o custo de inferência novamente — ver [09g](09g-cache-similaridade-clip.md).

## Arquitetura: backend → HTTP → Docker → GPU

```
FastAPI (`perfume-3d-backend/`)
    └── IntegratedPipeline
            └── Hunyuan3DProcessor
                    │  httpx.AsyncClient
                    │  POST /generate (multipart, 1-6 PNGs RGBA)
                    ▼
            Docker container (docker/hunyuan/)
                    │  FastAPI + uvicorn
                    │  Hunyuan3DDiTFlowMatchingPipeline  (shape)
                    │  Hunyuan3DPaintPipeline             (texture)
                    │  mmgp offload profile 4
                    ▼
            NVIDIA RTX 5050 8GB
                    │
                    ▼
            GLB binário com PBR → response body
```

O backend **não importa** `torch`, `transformers`, nem qualquer lib ML pesada. Toda a inferência fica no contêiner isolado, com sua própria versão de Python, CUDA 12.8 e dependências. A comunicação é puramente HTTP multipart.

## Parâmetros padrão (operacionalmente validados)

| Parâmetro | Valor | Observação |
|---|---|---|
| `octree_resolution` | 384 | Mais detalhe geométrico; cabe em 8GB com `mmgp profile 4`. |
| `num_inference_steps` | 75 | Equilíbrio entre estabilidade de superfície e tempo. |
| `guidance_scale` | 7.5 | CFG/guidance da forma. |
| `mc_algo` | `mc` | Marching Cubes clássico. `dmc` (Dual MC) foi tentado mas a `diso` falha no container (símbolo CUDA). O server faz fallback automático se `dmc` quebrar. |
| `texture_resolution` | 2048 | Textura multi-view quando disponível, single-view caso contrário. |
| `timeout_seconds` (cliente) | 1200 | 20 min — uma run com parâmetros pesados pode demorar 6–12 min na RTX 5050. |
| `service_url` | `http://localhost:7860` | Configurável via `HUNYUAN_URL` no `.env`. |
| checkpoint de forma | `tencent/Hunyuan3D-2mv/hunyuan3d-dit-v2-mv` (`fp16`) | Usa `front`, `left`, `back` e `right` na geometria. |
| fallback de forma | `tencent/Hunyuan3D-2/hunyuan3d-dit-v2-0` (`fp16`) | Modo degradado; usa somente a primeira imagem na geometria. |
| checkpoint de textura | `tencent/Hunyuan3D-2` | Independente do repositório de forma multi-view. |

Esses defaults vieram da sessão `historico/2026-05-09_integracao-sales-e-melhorias-hunyuan.md`.
O servidor pré-resolve o snapshot da forma solicitando somente `config.yaml` e
`model.fp16.safetensors`; o `.ckpt` duplicado do repositório não é necessário.

### Auditoria da configuração local em 2026-08-16

A configuração local auditada solicita `384 / 75 / 7.5 / mc` para a forma e
`1024` para a textura. **Ela não reduz a qualidade geométrica em relação aos
parâmetros operacionalmente validados do projeto.** A única redução solicitada
em relação ao default documentado acima é a textura de `2048` para `1024`, mas a
verificação ao vivo mostrou que o pipeline instalado ignora esse parâmetro no
caminho single-view efetivamente executado.

| Variável local | Papel técnico | Impacto esperado na qualidade |
|---|---|---|
| `HUNYUAN_URL=http://localhost:7860` | Endereço HTTP do serviço | Nenhum; muda somente a conexão. |
| `HUNYUAN_HOST_PORT=7860` | Porta exposta pelo Docker | Nenhum; muda somente a conexão. |
| `HUNYUAN_CACHE_VOLUME_NAME=tcc_hunyuan_cache` | Volume que conserva pesos baixados | Nenhum; evita novos downloads. Não é o cache de similaridade CLIP. |
| `HUNYUAN_TIMEOUT_SECONDS=1200` | Tempo máximo de espera do cliente | Não reduz qualidade. Se excedido, o job falha em vez de entregar uma malha de qualidade menor. |
| `HUNYUAN_OCTREE_RESOLUTION=384` | Resolução da grade hierárquica usada para extrair a superfície | É o modo **High** da interface oficial do Hunyuan3D-2. Pode preservar mais detalhe que `256`, com custo de VRAM, tempo e triângulos. |
| `HUNYUAN_NUM_INFERENCE_STEPS=75` | Número de iterações de remoção de ruído da geração da forma | Não é um valor reduzido; já é alto. Aumentar mais eleva o tempo e não implica ganho proporcional. |
| `HUNYUAN_GUIDANCE_SCALE=7.5` | Intensidade com que a forma é condicionada pelas imagens | É o valor usado no caminho multi-view oficial; não há evidência local de degradação por esse valor. |
| `HUNYUAN_MC_ALGO=mc` | Marching Cubes, algoritmo que converte o campo implícito em triângulos | Escolha estável. `dmc` é outra extração de superfície, não uma versão “completa” do modelo, e falhou neste contêiner por incompatibilidade da `diso`/CUDA. |
| `HUNYUAN_TEXTURE_RESOLUTION=1024` | Lado solicitado, em pixels, do mapa de textura | O valor não é efetivo no pipeline instalado: sua assinatura aceita apenas `(mesh, image)`, e o servidor omite `texture_resolution`. Assim, trocar `1024` por `2048` hoje não controla a resolução produzida. Isso não altera a geometria nem as métricas Chamfer, Hausdorff e F-Score. |

Referência externa: a interface oficial classifica a decodificação como
`Low=196`, `Standard=256` e `High=384` em
[`gradio_app.py`](https://github.com/Tencent-Hunyuan/Hunyuan3D-2/blob/main/gradio_app.py).

#### Valor solicitado não é necessariamente o valor efetivo

O cliente envia os cinco parâmetros no formulário HTTP, mas o servidor possui
degradações automáticas para conseguir terminar em GPU de 8 GB:

1. `_gerar_forma_com_fallback()` tenta o `octree_resolution` solicitado e, se
   ocorrer falta de VRAM ou não houver malha, tenta `octree=256, mc=mc`;
2. ao carregar os pesos, o servidor tenta o checkpoint multi-view e pode usar o
   checkpoint single-view se `HUNYUAN_ALLOW_SINGLE_VIEW_FALLBACK=1`;
3. `_texturizar_com_fallback()` tenta enviar uma lista de vistas, mas a classe de
   textura instalada espera uma única imagem PIL; todas as execuções registradas
   falharam nessa tentativa e continuaram apenas com a primeira foto;
4. a assinatura instalada também não possui `texture_resolution`; o helper
   `_filtrar_kwargs()` omite o argumento e deixa a biblioteca escolher sua
   resolução interna.

O segundo caso é o mais perigoso para fidelidade: em `shape_mode=single-view`,
as fotos esquerda, traseira e direita deixam de condicionar a geometria. Isso
pode prejudicar muito mais o formato do frasco que usar textura `1024`.

O `mmgp profile 4` realiza *offload* (movimenta partes do modelo entre RAM e VRAM
para caber na GPU). O offload, por si só, troca principalmente velocidade por
menor consumo de VRAM. A versão atual do projeto, porém, instala o fork e o
`mmgp` sem fixar commit ou versão no `Dockerfile`; portanto, uma reconstrução da
imagem pode mudar comportamento. A documentação atual do `mmgp` também informa
quantização de 8 bits por padrão em certos fluxos, mas não foi possível confirmar
se a imagem Docker local usa essa política. Esse possível impacto exige um teste
A/B e não deve ser apresentado como perda já comprovada.

#### Comprovação no contêiner em execução

Com o Docker em execução, verificar primeiro:

```powershell
Invoke-RestMethod http://localhost:7860/health
# Esperado: status=ready, shape_mode=multi-view, fallback=False

$container = docker ps --filter publish=7860 --format "{{.Names}}" |
  Select-Object -First 1
docker logs --tail=500 $container |
  Select-String -Pattern "Tentando forma|octree=256|Textura multi-view|usando primeira vista|texture-single|mmgp profile"
```

O contêiner `tcc-hunyuan-1` respondeu:

```text
status=ready
shape_mode=multi-view
shape_repo=tencent/Hunyuan3D-2mv
shape_subfolder=hunyuan3d-dit-v2-mv
shape_variant=fp16
fallback=False
```

Nos cinco jobs completos preservados nos logs, entre 23/07 e 06/08/2026:

- a forma recebeu `front`, `left`, `back` e `right`;
- executou `octree=384`, `steps=75`, `guidance=7.5`, `mc=mc`;
- chegou a `Forma gerada com sucesso` sem tentativa posterior em `256`;
- produziu entre 347.624 e 591.060 faces antes do pós-processamento;
- a textura multi-view falhou em todos com
  `'list' object has no attribute 'mode'`;
- o fallback usou a primeira imagem e registrou
  `texture-single nao aceita texture_resolution; omitindo`;
- todos concluíram a textura, exportaram GLB e responderam HTTP 200.

A inspeção Python confirmou que `Hunyuan3DPaintPipeline.__call__` possui a
assinatura `(self, mesh, image)`: a dependência instalada não oferece, nesse
contrato, lista de imagens nem parâmetro de resolução. O SHA-256 do `server.py`
no contêiner é igual ao arquivo do workspace, descartando imagem desatualizada
como causa. Portanto, o comportamento confirmado é **forma multi-view em 384 e
textura single-view com resolução interna não controlada pelo `.env`**.

#### Decisão recomendada para a RTX 5050 de 8 GB

- Manter `384 / 75 / 7.5 / mc` para a forma.
- Não esperar melhoria ao mudar apenas `1024 → 2048`: atualmente ambos os
  valores são omitidos. Um A/B de resolução só fará sentido depois que o
  pipeline de textura realmente aceitar e registrar o parâmetro efetivo.
- Tratar a textura atual como single-view. Para melhorar laterais e verso, será
  necessário integrar um pipeline que aceite múltiplas imagens ou ampliar as
  projeções por vista no Blender; isso é uma proposta, ainda não implementada.
- Avaliar a label projetada depois no Blender separadamente da pintura produzida
  pelo Hunyuan, pois esse estágio pode recuperar texto frontal mesmo quando a
  textura-base usa somente uma foto.
- Não usar `512` como default: o benchmark histórico do projeto registrou
  timeout superior a 30 minutos e fallback em vez de ganho utilizável.
- Em sessões longas, reiniciar o serviço entre lotes reduz o risco de
  fragmentação de VRAM. Se ainda houver OOM, `384 → 256` é uma degradação
  controlada, que deve ser registrada por job.

Analogia: a forma é uma escultura e a textura é a pintura aplicada sobre ela.
O `octree_resolution` é a finura da grade usada para recortar a escultura; a
`texture_resolution` é o tamanho da tela onde a pintura é desenhada. Assim,
reduzir `2048 → 1024` poderia borrar a pintura sem mudar a silhueta, **se o
controle fosse aceito**. No pipeline instalado, o pintor ignora esse tamanho e
usa sua configuração interna. A limitação da analogia é que forma e aparência
não são totalmente independentes na percepção humana: uma pintura ruim pode
fazer um modelo geometricamente bom parecer menos fiel.

#### Evidências e validação desta auditoria

Foram inspecionados `.env`, `.env.example`, `app/config.py`, `app/main.py`,
`app/modules/captures/processor.py`, `docker-compose.yml`,
`docker/hunyuan/server.py`, `docker/hunyuan/Dockerfile` e o histórico do
benchmark. O caminho confirmado é: configuração → construção do processor →
formulário HTTP → parâmetros da forma e da textura no servidor.

Teste executado:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest `
  tests/test_hunyuan_server.py `
  tests/modules/captures/test_processor.py `
  -q -p no:cacheprovider --basetemp=$env:TEMP\pytest-tcc
```

O `--basetemp` não é decorativo: sem ele, esta máquina falha os testes de
`test_processor.py` com `PermissionError: [WinError 5] Acesso negado` ao criar
`%LOCALAPPDATA%\Temp\pytest-of-crish`. É defeito de ambiente, não do código — os
mesmos testes passam quando o diretório temporário é gravável.

Resultado: **21 testes aprovados**. Eles validam o contrato do cliente e a lógica
do servidor com dependências simuladas, mas não medem qualidade perceptiva. A
consulta ao `/health`, a inspeção da assinatura instalada e os logs reais
complementaram os testes e comprovaram os caminhos efetivos descritos acima.
Ainda falta uma comparação visual controlada para quantificar o impacto da
textura single-view nos GLBs finais.

#### Hipótese avaliada e descartada: *bake* das fotos reais

A conclusão acima — "a textura usa uma foto só" — sugere naturalmente a correção
"então entregue as quatro fotos ao texturizador". Essa hipótese foi levantada,
implementada parcialmente e **descartada em 2026-08-16**. O registro fica aqui
porque o caminho é plausível à primeira vista e o motivo da rejeição não é óbvio.

A ideia era reproduzir o corpo de `Hunyuan3DPaintPipeline.__call__` substituindo
as vistas *sintetizadas* pelas quatro fotos *reais* e chamando
`bake_from_multiview` com os azimutes cardeais. A inspeção da biblioteca
instalada mostra por que isso não funciona:

1. `bake_from_multiview()` delega a `render.back_project(view, elev, azim)`, que
   rasteriza a malha a partir de uma câmera fixa e transfere pixel → UV. A
   imagem precisa ser um **render pixel-alinhado daquela malha naquela câmera**.
2. Essa câmera é **ortográfica** — `MeshRender(camera_distance=1.45,
   camera_type='orth')` com `ortho_scale=1.2`. Foto de celular é projeção
   **perspectiva**, com distância, distância focal e elevação desconhecidas. O
   pixel cai na geometria errada.
3. O `__call__` original só funciona porque o `multiview_model` gera as vistas
   *condicionadas* a `normal_maps` e `position_maps` renderizados da própria
   malha nesses mesmos ângulos: o alinhamento existe por construção, não por
   coincidência.

Ou seja, o pipeline aceita apenas uma foto de referência **por desenho**, não por
limitação de configuração. Aumentar o número de referências exige o checkpoint
multi-referência oficial (~14 GB, fora do orçamento de VRAM da RTX 5050 deste
projeto), não uma mudança de parâmetros. A alternativa por projeção geométrica no
Blender já existe no pipeline (topo, verso e label) e é discutida em
[17 - Fidelidade do modelo](17-fidelidade-do-modelo.md); ela não se aplica ao
corpo de frascos translúcidos, onde colar foto opaca destruiria a transmissão.

## Como subir o contêiner

Veja [docker/hunyuan/README.md](../docker/hunyuan/README.md) para instruções detalhadas. Resumo:

```bash
# Na raiz do repositório backend (C:\TCC\perfume-3d-backend):

# Build (20-40min na primeira vez — baixa ~5GB de pesos):
docker build -t perfume-hunyuan ./docker/hunyuan

# Run com GPU:
docker run --gpus all -p 7860:7860 perfume-hunyuan

# Ou via docker-compose (inclui postgres + volume persistente):
docker compose up hunyuan
```

A carga com cache pode levar cerca de 4–10 minutos. No primeiro uso, some o
download do checkpoint multi-view (~5 GB). Aguarde o principal ficar pronto:

```bash
curl http://localhost:7860/health
# → {"status":"ready","shape_mode":"multi-view",...,"fallback":false}
```

## Contrato HTTP do contêiner

- `GET /health` — retorna `loading`, `ready` ou `error`. Quando pronto, inclui
  `shape_mode`, `shape_repo`, `shape_subfolder`, `shape_variant` e `fallback`.
  O healthcheck do Compose só considera o contêiner saudável quando o corpo
  contém `status=ready`.
- `POST /generate` (multipart):
  - `images`: 1..6 arquivos (PNG RGBA preferencial; o servidor faz `convert("RGBA")` mas máscara pré-aplicada melhora a qualidade do mesh).
  - `octree_resolution`, `num_inference_steps`, `guidance_scale`, `mc_algo`, `texture_resolution` — todos como `Form`.
  - **Resposta**: `model/gltf-binary` (GLB bruto). Header `Content-Type` confirma o formato.

O cliente Python valida o magic header `b"glTF"` antes de gravar em disco; se vier outra coisa, levanta `ProcessingError`.

## Pré-requisitos antes de chamar

O `IntegratedPipeline` garante isto, mas se você instanciar o processor solo:

- Serviço Hunyuan (`docker compose up hunyuan`) rodando e com modelo carregado (`/health → ready`).
- Imagens **pré-segmentadas** pelo `RembgBackgroundRemover` (Hunyuan inclui fundo como geometria se receber JPEG cru).
- Resolução das imagens ≤ 2048 px no maior lado (Hunyuan não consome mais que isso).

`template_id`, `liquid_color` e `label_image` do `ProcessingInput` são **ignorados** pelo `Hunyuan3DProcessor`. A integração com esses campos acontece em outros stages do pipeline:

- `liquid_color`: a cor é inferida pelo Hunyuan a partir das fotos; persistida como metadado em `modelos_3d_universais.liquid_color` se você quiser.
- `label_image`: o `IntegratedPipeline` extrai a label real via `LabelExtractor` e a projeta com `LabelProjector` no GLB do Hunyuan.

## Trade-offs: Hunyuan3D vs o antigo caminho de templates

> Comparação histórica. O `TemplateProcessor` foi removido em 2026-08; a tabela documenta por que o caminho de IA venceu.

| | `TemplateProcessor` (removido) | `Hunyuan3DProcessor` (único) |
|---|---|---|
| Tempo por job (miss) | ~10s (Blender headless) | 3–8min (IA na GPU) |
| Tempo por job (hit do cache) | n/a | ~5s (cópia do GLB) |
| VRAM necessária | 0 (só CPU) | ~6-8GB (profile 4) |
| Templates pré-existentes? | Sim (GLB por forma) | Não |
| Qualidade (frascos conhecidos) | Alta (geometria exata) | Boa (estimativa IA) |
| Qualidade (frascos novos) | Depende do template mais próximo | Razoável |
| Textura da label | `LabelExtractor` + Blender (decal) | Inferida das fotos pelo Hunyuan, depois substituída pelo decal do `LabelProjector` (ver [09e](09e-aplicacao-label.md)) |
| Cor do líquido | Veio do `AverageColorDetector` (depreciado) ou metadado do cache | Inferida pelo Hunyuan |

## Falhas e degrade

Dentro do `IntegratedPipeline`, falhas do Hunyuan caem em duas categorias:

1. **Recuperáveis no próprio contêiner** (server.py faz fallback): checkpoint de
   forma multi-view → single-view de outro repositório, `dmc → mc`, octree
   `384 → 256`, textura multi-view → single-view e lista vazia
   (`PipelineSemMalhaError`). O `/health` revela quando o fallback de checkpoint
   foi usado.
2. **Não recuperáveis** (`/health` não responde, timeout do cliente, GLB inválido): o pipeline integrado decide entre:
   - Sem fallback: a falha é preservada como sinal de problema operacional e o job vai para `error`.
   - Marcar o job como `error` com mensagem específica.

## Limitações conhecidas

- **Vidro translúcido**: o Hunyuan3D-2mv trata vidro como superfície opaca azulada. O `BlenderMeshRefiner` resolve isso aplicando shader PBR (ver [09c](09c-refinamento-mesh.md)).
- **Tampa**: em frascos com tampa destacada, o modelo pode fundir a tampa ao corpo dependendo do ângulo das fotos. Fotos com a tampa claramente separada ajudam; ângulo da câmera importa.
- **Fundo não removido**: enviar fotos sem `RembgBackgroundRemover` degrada significativamente a qualidade — o modelo inclui partes do fundo como geometria.
- **Tempo de geração**: 3–8 min inviabiliza uso síncrono; o cache + a fila do `CaptureService` mitigam isso.
- **Texto da label**: Hunyuan inventa texto. Por isso o pipeline integra `LabelExtractor` + `LabelProjector` (ver [09e](09e-aplicacao-label.md)).

## Leituras relacionadas

- [09 — Pipeline 3D (abstração `Processor`)](09-pipeline-3d.md)
- [09c — Refinamento de malha (shader de vidro PBR)](09c-refinamento-mesh.md)
- [09d — Pré-processamento e cleanup](09d-preprocessamento-e-cleanup.md)
- [09e — Aplicação de label](09e-aplicacao-label.md)
- [09f — Pipeline integrado (composição)](09f-pipeline-integrado.md)
- [09g — Cache de similaridade CLIP](09g-cache-similaridade-clip.md)
- [10b — Segmentação e extração de label](10b-segmentacao-e-label.md) (entrada do Hunyuan)
- Código: [`app/modules/captures/processor.py`](../app/modules/captures/processor.py) (classe `Hunyuan3DProcessor`)
- Docker: [`docker/hunyuan/`](../docker/hunyuan/) (Dockerfile, server.py, README)
