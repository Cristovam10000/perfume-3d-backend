# Sessao 2026-05-09 — Validacao smoke Hunyuan e documentacao cronologica

## 1. Metadados

- **Titulo:** Validacao operacional dos smokes Hunyuan/Fase 5 e documentacao cronologica para o TCC.
- **Data aproximada:** 2026-05-09, inferida pelo commit `724915c`. A base tecnica validada nesta sessao tambem depende de `6e6f212` (2026-04-28) e `df843ca` (2026-04-29).
- **Fase do projeto:** pos-Fase 5, com foco em validacao manual, diagnostico operacional e organizacao metodologica do historico academico.
- **Escopo principal:** registrar a conversa em que foram revisados os smokes reais do pipeline IA, problemas de Docker/Hunyuan, RAM/VRAM, visualizacao de GLBs, timeout do Hunyuan e a propria criacao de um historico auditavel por Git.
- **Posicionamento cronologico inferido:** sessao documentada #7. Ela ocorre depois de `historico/2026-05-09_integracao-sales-e-melhorias-hunyuan.md`, mas e parcialmente paralela a ela, porque ambas se apoiam no commit `724915c`. A diferenca e de escopo: a sessao anterior registra integracao comercial e ajustes Hunyuan; esta registra validacao operacional, interpretacao dos smokes e consolidacao do historico.
- **Commits Git associados:**
  - `6e6f212` — 2026-04-28 — introduz `ImagePreprocessor`, `MeshCleaner`, `LabelUpscaler`, `LabelProjector`, `smoke_phase4.py`, `smoke_phase5.py`, docs `09d` e `09e`.
  - `df843ca` — 2026-04-29 — ajusta `scripts/smoke_phase5.py` com parametros configuraveis do Hunyuan e tratamento de erro/timeout mais explicito.
  - `724915c` — 2026-05-09 — adiciona modulo `sales` e tambem toca `processor.py`, smokes e teste real do Hunyuan; e a ancora cronologica mais recente desta sessao.
  - `historico/*` — sem commit proprio no momento da redacao; `git status` mostra a pasta `historico/` como nao rastreada.
- **Sessoes anteriores referenciadas:**
  - `historico/2026-04-26_preparacao-blender-templates.md`
  - `historico/2026-04-26_fase2-templates-clip-cor.md`
  - `historico/2026-04-26_validacao-e2e-mobile-viewer-local.md`
  - `historico/2026-05-09_pipeline-ia-segmentacao-e-refinamento.md`
  - `historico/2026-04-28_fase4-fase5-preprocessamento-cleanup-label.md`
  - `historico/2026-05-09_integracao-sales-e-melhorias-hunyuan.md`

## 2. Contexto inicial

O projeto estava organizado como um monolito modular FastAPI em `back/`, mas `C:\TCC` em si nao era um repositorio Git unico. A raiz Git efetiva era `C:\TCC\back`; `docker/` e `front/` estavam fora do historico Git do backend, embora fossem parte operacional do projeto.

Antes desta sessao, as fases tecnicas ja estavam implementadas em commits anteriores:

- Fases 1 a 3: remocao de fundo, extracao de label por homografia, geracao GLB via Hunyuan3D em Docker e refinamento de shader de vidro.
- Fase 4: preprocessamento de imagens e limpeza conservadora de malha.
- Fase 5: upscale Lanczos da label e projecao planar no GLB via Blender.
- Smokes manuais: `scripts/smoke_phase3.py`, `scripts/smoke_phase4.py` e `scripts/smoke_phase5.py`.

A motivacao imediata foi dupla. Primeiro, havia necessidade pratica de validar visualmente o resultado real do pipeline IA com fotos de perfume, incluindo a versao crua, limpa/refinada e com label projetada. Segundo, como o projeto e um TCC em fase de pre-projeto, surgiu a necessidade de documentar a sessao com rigor academico, cruzando conversa, arquivos existentes em `historico/` e commits reais.

## 3. Decisoes arquiteturais e de design

### Git como fonte primaria da cronologia

Foi decidido que a cronologia do historico deve priorizar o Git. A conversa e os arquivos `historico/` ajudam a interpretar contexto, mas os commits sao a ancora dura. Isso confirma a convencao ja registrada em `historico/INDEX.md`: a data do arquivo historico deve seguir a data inferida pelos commits, nao a data em que o texto foi escrito.

Uma divergencia importante foi registrada: `historico/2026-05-09_pipeline-ia-segmentacao-e-refinamento.md` descreve commits de 2026-04-27, mas tem nome com 2026-05-09. O indice ja trata isso como divergencia consciente; esta sessao preserva a decisao e nao tenta reescrever artificialmente a linha do tempo.

### Separacao entre implementacao, validacao e operacao

Durante a sessao ficou claro que algumas mudancas estavam implementadas em commits anteriores, enquanto a conversa atual estava validando e diagnosticando comportamento em ambiente real. Por isso, este documento evita dizer que tudo foi "implementado nesta sessao". A classificacao adotada foi:

- **Implementado em `6e6f212`:** componentes das Fases 4 e 5.
- **Ajustado em `df843ca`:** parametrizacao e erros do `smoke_phase5`.
- **Reancorado em `724915c`:** ajustes recentes de Hunyuan/testes e contexto operacional.
- **Documentado agora:** interpretacao academica, pendencias e indice historico.

### Cleaner conservador por padrao

A validacao visual mostrou que a limpeza agressiva de ilhas podia piorar o GLB do Hunyuan, gerando pontos brancos e artefatos. A decisao tecnica consolidada foi manter `min_island_ratio=0.0` como caminho conservador: o cleaner copia o GLB sem chamar Blender quando esse ratio e zero. Essa escolha privilegia preservacao visual em vez de remocao automatica arriscada de fragmentos.

Essa decisao modifica a expectativa inicial da Fase 4, que pressupunha que "limpar" sempre melhoraria a malha. O resultado empirico mostrou que, para Hunyuan, pequenas ilhas podem fazer parte de superficies uteis ou texturas fragmentadas.

### `--no-label` nao significa "sem textura do Hunyuan"

Foi esclarecido que `--no-label` no `smoke_phase5.py` desativa apenas a extracao/projecao da label real pelo backend. Ele nao desliga a textura interna gerada pelo Hunyuan. Portanto, um smoke com `--no-label` ainda pode demorar ou falhar por causa da etapa de texturizacao do Hunyuan, dependendo das variaveis do container, memoria disponivel e parametros de inferencia.

### Timeouts explicitos em vez de erro silencioso

Quando o smoke falhou apos aproximadamente 901 segundos com `ERRO:` vazio, a interpretacao foi que o Hunyuan excedeu o timeout do cliente ou fechou a conexao sem uma mensagem util. A decisao registrada em `df843ca` e reforcada nesta sessao foi expor parametros como:

```powershell
--hunyuan-timeout-seconds
--octree-resolution
--num-inference-steps
```

Isso permite transformar uma falha opaca em uma execucao reprodutivel: menos passos/resolucao para teste rapido, mais timeout para execucao final.

### Teste real do Hunyuan como opt-in

O teste `tests/integration/test_hunyuan_real.py` falhou em suite completa porque depende de container Hunyuan real e pode levar muitos minutos. A decisao consolidada foi deixa-lo como teste lento e opt-in via `RUN_HUNYUAN_REAL=1`, para nao quebrar `pytest` em ambientes sem GPU/container pronto.

## 4. Implementacao realizada

Esta sessao nao introduziu novo commit de codigo-fonte no momento da redacao; ela documenta e valida implementacoes ja presentes no historico Git. Os arquivos tecnicos relevantes sao:

- `app/modules/captures/image_preprocessor.py` — preprocessamento de fotos antes do Hunyuan, criado em `6e6f212`.
- `app/modules/captures/mesh_cleaner.py` — cleaner com bypass quando `min_island_ratio <= 0.0`, criado em `6e6f212` e usado na validacao conservadora.
- `app/modules/captures/label_upscaler.py` — upscale Lanczos da label, criado em `6e6f212`.
- `app/modules/captures/label_projector.py` — wrapper Python do projetor Blender, criado em `6e6f212`.
- `app/modules/captures/blender_scripts/project_label.py` — script Blender para deteccao de face frontal e projecao da label, criado em `6e6f212`.
- `scripts/smoke_phase5.py` — smoke manual da Fase 5, criado em `6e6f212`, aprimorado em `df843ca` e tocado novamente em `724915c`.
- `tests/integration/test_hunyuan_real.py` — teste real do Hunyuan, marcado como `slow` e opt-in por variavel de ambiente.
- `docs/09e-aplicacao-label.md` — documentacao tecnica da aplicacao de label.
- `historico/2026-05-09_validacao-smoke-hunyuan-e-documentacao-cronologica.md` — registro criado nesta sessao.
- `historico/INDEX.md` — indice geral atualizado nesta sessao.

Do ponto de vista operacional, a sessao consolidou comandos de uso:

```powershell
cd C:\TCC\back
.\.venv\Scripts\python.exe scripts\smoke_phase5.py "C:\caminho\das\fotos" --open
.\.venv\Scripts\python.exe scripts\smoke_phase5.py "C:\caminho\das\fotos" --reuse-raw --open
.\.venv\Scripts\python.exe scripts\smoke_phase5.py "C:\caminho\das\fotos" --no-label --hunyuan-timeout-seconds 1800 --octree-resolution 128 --num-inference-steps 20
```

Tambem foi consolidada a forma correta de visualizar os GLBs quando servidos por `storage/model_viewer.html`:

```text
http://localhost:8000/model_viewer.html?src=%2Fsmoke%2Fraw.glb
http://localhost:8000/model_viewer.html?src=%2Fsmoke%2Frefined.glb
http://localhost:8000/model_viewer.html?src=%2Fsmoke%2Fwith_label.glb
```

## 5. Problemas encontrados e solucoes

### Links 404 no viewer

O smoke imprimia links que podiam ser confundidos entre montagem FastAPI (`/files/...`) e servidor estatico simples na pasta `storage`. Quando o usuario abriu `http://localhost:8000/files/model_viewer.html?...`, o navegador retornou 404. A solucao operacional foi usar o viewer na raiz do servidor estatico:

```text
http://localhost:8000/model_viewer.html?src=%2Fsmoke%2Frefined.glb
```

Esse problema nao era do GLB; era de rota/servidor.

### Raw e refined pareciam iguais

Ao comparar `raw.glb` e `refined.glb` no `model_viewer`, a diferenca visual foi pequena. A interpretacao foi que o refinamento de shader altera propriedades materiais, mas o viewer web pode nao evidenciar bem transmissao/IOR do vidro, especialmente quando a malha e a textura gerada pelo Hunyuan continuam dominando a aparencia. A versao final para o usuario deve ser a mais avancada disponivel no pipeline (`with_label.glb` quando a label for projetada; `refined.glb` quando nao houver label).

### Pontos brancos apos cleanup

O usuario observou que o `raw.glb` estava visualmente melhor e que os pontos brancos apareciam apos o `cleaned.glb`. Isso mudou a interpretacao inicial: o problema nao vinha necessariamente da IA geradora, mas da etapa de limpeza removendo ou expondo fragmentos de material de forma ruim. A solucao foi tornar o cleanup conservador e permitir bypass com `min_island_ratio=0.0`.

### LabelExtractor nao encontrava label em perfume com texto impresso no vidro

O `HomographyLabelExtractor` foi desenhado para localizar labels retangulares. No perfume validado, o texto parecia impresso diretamente no frasco, sem quadrilatero forte. A homografia nao encontrou uma label plausivel. A solucao adotada no smoke foi modo degradado/fallback por recorte central/direito e a possibilidade de usar `--label-image` para fornecer uma label recortada manualmente.

### Hunyuan falhou apos 901 segundos

Em um teste com `C:\TCC\imagens para teste`, o smoke falhou em `(5/8) gerando GLB no Hunyuan` apos cerca de 901 segundos, com mensagem vazia. A investigacao separou tres pontos:

- O endpoint `/health` podia estar `ready`, entao o container estava vivo.
- `--no-label` nao desligava a textura do Hunyuan.
- Sem `raw.glb` novo em `tmp/smoke`, a falha ocorreu antes de finalizar a resposta `/generate`.

A solucao operacional sugerida foi rodar com timeout maior e parametros mais leves:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_phase5.py "C:\TCC\imagens para teste" --max-images 4 --no-label --open --hunyuan-timeout-seconds 1800 --octree-resolution 128 --num-inference-steps 20
```

Para diagnostico, tambem foi indicado consultar logs do container:

```powershell
docker logs --tail 120 tcc-hunyuan-1
```

### Duvida sobre internet

Foi esclarecido que a geracao GLB nao deveria depender da internet depois que pesos e caches do Hunyuan estao presentes no container/volume. A internet e necessaria principalmente no primeiro build/download ou se algum cache/modelo estiver ausente. Quando `/health` retorna `ready`, uma falha de `/generate` e mais provavelmente timeout, OOM, parametros pesados ou erro interno de inferencia, nao falta de internet.

### RAM/VRAM e risco para GPU

A sessao registrou que aumentar `HUNYUAN_VRAM_BUDGET_MB` pode deslocar parte da carga para VRAM, mas nao elimina uso de RAM. Tambem foi esclarecido que usar VRAM demais nao "queima" a placa de video; o risco pratico e OOM, reset de driver, travamento temporario da tarefa, queda do container ou lentidao do sistema.

### Pytest completo com teste real do Hunyuan

O `pytest -q` falhou uma vez em `tests/integration/test_hunyuan_real.py` por `httpx.ReadTimeout`. A solucao consolidada foi manter esse teste como manual/opt-in com `RUN_HUNYUAN_REAL=1`, evitando que uma suite local sem garantia de GPU/container trave por dependencia externa.

## 6. Conceitos teoricos envolvidos

- **Rastreabilidade por controle de versao:** uso de commits como fonte primaria para reconstruir a evolucao tecnica.
- **Testes smoke:** validacao ponta a ponta com baixo nivel de assercao automatica, adequada para pipelines com componentes visuais e IA generativa.
- **Testes lentos opt-in:** separacao entre testes deterministas de unidade/integracao leve e testes que exigem GPU, Docker ou servico externo.
- **Pipelines degradaveis:** quando uma etapa falha (ex.: label nao detectada), o sistema pode continuar com resultado parcial (`refined.glb`) em vez de abortar todo o fluxo.
- **Heuristicas visuais:** deteccao de label por homografia, fallback por recorte, deteccao de corpo/face frontal por geometria e materiais.
- **Trade-off entre limpeza automatica e preservacao visual:** remocao de ilhas pode reduzir ruido geometrico, mas tambem destruir detalhes uteis quando a malha vem de IA generativa.
- **Gestao de recursos em inferencia local:** VRAM, RAM, timeout, resolucao de octree e numero de passos influenciam diretamente estabilidade e tempo de execucao.
- **Reprodutibilidade academica:** comandos, hashes, arquivos e logs permitem reexecutar ou auditar a decisao no futuro.

## 7. Pendencias e proximos passos

### Releitura das pendencias anteriores

- ✅ **Formalizar viewer local** — registrada em `historico/2026-04-26_validacao-e2e-mobile-viewer-local.md`; foi cumprida anteriormente com `storage/model_viewer.html` e reforcada nesta sessao com os links corretos.
- ✅ **Label segmentation / nao usar primeira foto inteira como label** — pendencia de `historico/2026-04-26_fase2-templates-clip-cor.md`; foi cumprida tecnicamente em `6e6f212` com `LabelUpscaler` e `LabelProjector`, mas a validacao mostrou que a extracao automatica ainda falha em frascos sem etiqueta retangular.
- ✅ **Fase 5 de aplicacao de label** — pendencia implicita das sessoes de pipeline IA; implementada em `6e6f212`.
- 🔄 **Validacao visual real do pipeline IA** — pendente em `historico/2026-05-09_pipeline-ia-segmentacao-e-refinamento.md` e `historico/2026-04-28_fase4-fase5-preprocessamento-cleanup-label.md`; foi parcialmente cumprida por smokes manuais, mas ainda precisa virar evidencia formal com imagens comparativas e criterios de avaliacao.
- 🔄 **Limitacoes do Hunyuan em vidro/textura** — pendencia de `historico/2026-05-09_pipeline-ia-segmentacao-e-refinamento.md`; parcialmente mitigada por refiner e label projector, mas persistem falhas de textura, tempo e qualidade em casos reais.
- 🔄 **Empirical validation do `LabelExtractor`** — parcialmente exercitada: a sessao mostrou uma falha relevante em perfume com texto impresso no vidro e motivou fallback/manual crop. Ainda falta uma bateria sistematica com varias fotos.
- 🔄 **Configurar parametros Hunyuan por ambiente** — parcialmente enderecado por variaveis e flags (`HUNYUAN_ENABLE_TEXTURE`, `HUNYUAN_VRAM_BUDGET_MB`, timeout/octree/steps), mas ainda falta configuracao integrada no backend principal.
- ⏳ **Compor Hunyuan + cleanup + refiner + label no `CaptureService`** — ainda pendente desde `historico/2026-05-09_pipeline-ia-segmentacao-e-refinamento.md` e `historico/2026-04-28_fase4-fase5-preprocessamento-cleanup-label.md`. Os smokes validam os componentes, mas o fluxo HTTP oficial ainda nao usa a cadeia completa.
- ⏳ **Separar testes slow no CI** — ainda pendente. `test_hunyuan_real.py` foi tornado opt-in, mas falta politica formal de CI para `pytest -m slow`.
- ⏳ **Persistir metadados de processamento 3D** — pendencia de `historico/2026-04-26_validacao-e2e-mobile-viewer-local.md`; segue valida.
- ⏳ **Criar benchmark visual/criterio objetivo de parecido** — pendente em sessoes anteriores; esta sessao reforca a necessidade, porque "ficou ruim" foi observado visualmente, mas sem metrica formal.
- ⏳ **Validar CLIP/classificador em casos reais** — pendencia da Fase 2; nao foi tratada nesta sessao.
- ⏳ **GPU PyTorch para CLIP no host** — pendencia da Fase 2; nao foi tratada.
- ⏳ **Tratamento de frascos transparentes/neutros** — pendencia da Fase 2; continua relevante.
- ⏳ **Versionar mudancas fora de `back`** — pendencia reforcada em `historico/2026-05-09_integracao-sales-e-melhorias-hunyuan.md`; `docker/` e `front/` continuam fora do Git do backend.
- ⏳ **Confirmar build aplicado no container Hunyuan** — pendencia operacional ainda valida, especialmente quando variaveis de textura/VRAM parecem nao produzir efeito esperado.
- ⏳ **Decidir futuro do `dmc` vs `mc`** — pendencia de Hunyuan registrada anteriormente; nao foi resolvida nesta sessao.

### Novas pendencias geradas nesta sessao

- Versionar ou mover formalmente a pasta `historico/`, que no momento aparece como nao rastreada em `git status`.
- Salvar evidencias visuais dos smokes: screenshots de `raw.glb`, `cleaned.glb`, `refined.glb` e `with_label.glb`, com data, comando usado e parametros.
- Adicionar ao smoke um aviso mais claro de que `--no-label` nao desativa texturizacao do Hunyuan.
- Considerar uma flag explicita para smoke sem textura Hunyuan, caso o servidor aceite esse controle por variavel ou parametro.
- Registrar logs do container Hunyuan como artefatos de diagnostico quando `/generate` exceder timeout.
- Documentar um protocolo de memoria para maquina de 16 GB RAM/8 GB VRAM: limites recomendados, sinais de OOM e parametros leves para smoke rapido.
- Avaliar se `smoke_phase5.py` deve sugerir automaticamente `--reuse-raw` quando `tmp/smoke/raw.glb` ja existir.

## 8. Reflexao para o TCC

Esta sessao mostra uma mudanca metodologica importante: o projeto deixou de ser apenas desenvolvimento incremental de funcionalidades e passou a exigir rastreabilidade academica. O mesmo pipeline que parecia "pronto" nos testes unitarios revelou novos problemas quando executado em condicoes reais: timeout do Hunyuan, custo de textura, diferenca entre raw e cleaned, falha de homografia em label nao-retangular e confusao entre rotas de visualizacao.

O aprendizado principal e que, para um TCC com IA generativa e 3D, a qualidade final nao pode ser demonstrada apenas por testes automatizados. E necessario combinar hashes Git, testes unitarios, smokes manuais, capturas visuais, logs de execucao e analise critica das falhas. Nesse sentido, os erros encontrados nao sao apenas obstaculos; eles ajudam a delimitar o escopo cientifico do trabalho e a justificar decisoes pragmaticas como Lanczos em vez de Real-ESRGAN, cleaner conservador em vez de remocao agressiva e testes Hunyuan como opt-in.

Tambem ficou claro que a fronteira entre "backend", "Docker" e "modelo IA" precisa ser explicitada no texto do TCC. Um erro HTTP 500 ou timeout pode vir de memoria, parametros de inferencia, container, textura, cache de modelo ou cliente HTTP. Documentar essas possibilidades torna o trabalho mais defensavel e evita que a avaliacao dependa apenas de uma demonstracao ao vivo.
