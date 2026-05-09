# Validação E2E Mobile e Viewer Local

## 1. Metadados

- **Título:** Validação E2E mobile, depuração Android/Windows e viewer local para inspeção de GLB.
- **Data aproximada:** 2026-04-26, inferida pelos commits Git associados.
- **Fase do projeto:** fechamento empírico da Fase 2 / Etapa 16, imediatamente após templates, CLIP e detector de cor entrarem no pipeline operacional.
- **Escopo principal:** executar o fluxo real pelo app Flutter, diagnosticar falhas de conectividade, subprocess Blender no Windows, WebView Android, seleção de imagens da galeria e qualidade visual do GLB resultante; em seguida, criar um caminho de inspeção no notebook por `model_viewer.html`.
- **Posicionamento cronológico inferido:** sessão **2** no conjunto documentado, como complemento direto da sessão `historico/2026-04-26_fase2-templates-clip-cor.md`. O Git indica que os commits principais desta validação ocorreram em 2026-04-26, depois dos commits de templates/processor e antes do pipeline IA de 2026-04-27. Parte dos commits backend também aparece no documento da Fase 2 porque aquele arquivo agregou a implementação e o início da validação; aqui o foco é o ciclo E2E mobile/notebook.
- **Observação sobre repositórios:** `C:\TCC` não é um repositório Git único. Há pelo menos dois repositórios relevantes: `back` e `front`. O histórico acadêmico existente está em `back/historico/`; por continuidade, este documento também foi criado ali, mas referencia commits dos dois repositórios.

### Commits Git associados

Backend (`C:\TCC\back`):

| Hash | Data | Papel nesta sessão |
|---|---|---|
| `f073dbb` | 2026-04-26 | Pré-requisito imediato: `TemplateProcessor`, `PROCESSOR_TYPE`, `BLENDER_EXECUTABLE`, `TEMPLATES_DIR` e factory `build_processor`. |
| `1a46a0e` | 2026-04-26 | Pré-requisito imediato: `Classifier` ABC, `DisabledClassifier`, `CLIPClassifier` e catálogo textual de templates. |
| `1d4ec12` | 2026-04-26 | Pré-requisito imediato: `ColorDetector`, `DisabledColorDetector`, `AverageColorDetector` com filtro cromático. |
| `30e1d8d` | 2026-04-26 | Integra classificação/cor no `CaptureService`, remove aplicação automática da primeira foto como label, expõe `/templates/` e corrige subprocess Blender no Windows. |
| `338d935` | 2026-04-26 | Cria `storage/model_viewer.html` para inspecionar GLBs no notebook sem depender do app mobile. |
| `5a7663d` | 2026-04-26 | Gera template procedural `feeling_rectangular_blue` e previews para aproximar o frasco Hinode Feelin' Flame. |

Frontend (`C:\TCC\front`):

| Hash | Data | Papel nesta sessão |
|---|---|---|
| `91eaaaa` | 2026-04-26 | Ajusta `AppConstants.backendBaseUrl` para desenvolvimento local em rede. |
| `f0537cb` | 2026-04-26 | Corrige fluxo de retry, seleção/recuperação de imagens da galeria e permissões Android para HTTP/WebView. |

### Sessões anteriores referenciadas

- `historico/2026-04-26_fase2-templates-clip-cor.md`: pré-requisito lógico. Documenta templates normalizados, `TemplateProcessor`, `CLIPClassifier`, `AverageColorDetector` e o início da Etapa 16.
- Bootstrap sem documento, commits `b724648` → `0106a1f`: base FastAPI, `FakeProcessor`, fila asyncio, rotas `POST /captures` e `GET /captures/{id}/status`.

Documentos já existentes, mas cronologicamente posteriores por Git:

- `historico/2026-05-09_pipeline-ia-segmentacao-e-refinamento.md`: nome de arquivo posterior, mas commits de 2026-04-27. Registra a virada para pipeline IA.
- `historico/2026-04-28_fase4-fase5-preprocessamento-cleanup-label.md`: commits de 2026-04-28/29. Registra pré-processamento, limpeza de malha e projeção de label.

## 2. Contexto inicial

Antes desta sessão, o backend já tinha uma arquitetura plugável baseada em `Processor`, com `FakeProcessor` para MVP rápido e `TemplateProcessor` para customizar GLBs via Blender headless. A Fase 2 havia acrescentado templates normalizados, classificação zero-shot por CLIP e detecção média de cor do líquido.

O app Flutter já possuía fluxo de captura/revisão/envio/status/viewer. A expectativa era executar o teste manual da Etapa 16 com um perfume real: capturar ou selecionar várias fotos no celular, enviar para `POST /captures`, acompanhar polling em `GET /captures/{id}/status` e visualizar o GLB no viewer.

A motivação prática da sessão foi verificar se a pipeline "sai da bancada": não bastava os testes unitários estarem verdes. Era necessário confirmar conectividade celular-notebook, execução real do Blender, abertura do modelo no Android e fidelidade visual mínima do resultado.

## 3. Decisões arquiteturais e de design

### 3.1 Usar IP da rede local para o app mobile

O erro inicial no app foi `No route to host`. A causa provável era o celular tentando acessar um endereço de backend que não correspondia ao IP atual do notebook na rede Wi-Fi. Para celular físico, `localhost`/`127.0.0.1` aponta para o próprio aparelho, não para o notebook.

A decisão foi manter o backend ouvindo em `0.0.0.0:8000`, mas configurar o Flutter para usar o IPv4 do notebook na rede local. Essa decisão aparece no frontend em `91eaaaa` e depois é reforçada no fluxo de depuração da sessão.

Trade-off: endereço IP fixo no código é frágil quando a rede muda. Para o MVP local, acelera o teste; para uma versão reprodutível, o ideal é flavor/env config ou descoberta configurável.

### 3.2 Corrigir subprocess Blender por compatibilidade Windows

O backend falhou com `NotImplementedError` em `asyncio.create_subprocess_exec`. O stack trace apontou para a implementação de subprocess assíncrono do event loop no Windows.

A decisão foi trocar a execução do Blender para `subprocess.run` dentro de `asyncio.to_thread`:

```python
return await asyncio.to_thread(self._run_blender_sync, args)
```

Essa solução preserva a API assíncrona do `Processor`, evita bloquear o event loop principal da aplicação e contorna a ausência de suporte do loop corrente para subprocess nativo.

Trade-off: o stdout/stderr são coletados ao final do processo, não streamados em tempo real. Para a necessidade desta fase, a robustez em Windows era mais importante que streaming incremental de logs.

### 3.3 Retry de job com erro não deve apenas reiniciar polling

O botão "Tentar novamente" reaproveitava o mesmo `jobId`. Como o job já estava marcado como erro, a tela apenas fazia novas requisições de status para um estado terminal. A decisão foi mudar o texto e a semântica para "Revisar e reenviar": resetar o estado de processamento e voltar para a revisão/captura, permitindo novo upload e novo job.

Essa decisão aparece no frontend em `f0537cb`, no arquivo `lib/features/processing/presentation/pages/processing_status_page.dart`.

### 3.4 Permitir HTTP/cleartext no Android apenas para o ambiente local

O viewer mobile exibiu `net::ERR_CLEARTEXT_NOT_PERMITTED` ao tentar abrir uma URL HTTP local. A decisão foi adicionar `android.permission.INTERNET` e `android:usesCleartextTraffic="true"` no `AndroidManifest.xml`.

Trade-off: liberar tráfego sem TLS não é apropriado para produção. Aqui foi aceito por se tratar de ambiente local de TCC/MVP, com backend em rede privada e URLs HTTP geradas pelo servidor de desenvolvimento.

### 3.5 Separar depuração de GLB da depuração mobile

O resultado visual ruim no celular misturava várias incertezas: pipeline de modelagem, URL, WebView, rede e app Flutter. A decisão foi criar um viewer local servível pelo próprio backend (`/files/model_viewer.html`) usando `@google/model-viewer`, permitindo abrir e comparar GLBs no notebook.

Essa decisão reduziu o custo de iteração: depois que o GLB é gerado, a inspeção visual não precisa passar pelo celular.

### 3.6 Não aplicar a primeira foto como label automaticamente

O comportamento anterior do `TemplateProcessor` colava a primeira foto enviada como textura de label quando `label_image` era `None`. No teste real, isso produziu artefato visual grave: a foto inteira, com fundo e perspectiva, aparecia como um retângulo no modelo.

A decisão foi exigir `label_image` explícito. Enquanto não houver extração de label, o template fica sem textura real em vez de aplicar uma textura sabidamente errada.

Essa decisão modifica uma suposição implícita da sessão `2026-04-26_fase2-templates-clip-cor.md`: o pipeline de templates não deve improvisar label a partir da foto crua.

### 3.7 Tratar erro de classificação como limite empírico, não só bug

O perfume real testado tinha frasco azul-escuro retangular com tampa preta, mas a classificação CLIP chegou a selecionar templates genéricos como `cylindrical_basic` ou `square_compact`. A sessão mostrou que o problema era parcialmente técnico (orientação EXIF/cor/label), mas também de cobertura do catálogo: os templates disponíveis não representavam bem aquele produto.

A decisão foi criar o template procedural `feeling_rectangular_blue` para o caso Hinode Feelin' Flame, em vez de tentar forçar templates genéricos a parecerem com um frasco específico.

Trade-off: um template procedural melhora muito um caso conhecido, mas é menos geral. Essa limitação motivou, nas sessões posteriores, a exploração de geração 3D por IA.

### 3.8 Robustecer a seleção de galeria como estado de UI

O erro `PlatformException(already_active, Image picker is already active)` indicou concorrência entre abertura da galeria, retorno do picker e nova tentativa do usuário. A decisão foi transformar a seleção em estado explícito (`selectingFromGallery`), desabilitar o botão durante a operação, pausar o stream da câmera e recuperar seleção perdida com `retrieveLostData`.

Essa solução trata o picker como operação modal assíncrona, não como chamada instantânea.

## 4. Implementação realizada

### 4.1 Backend

- `app/modules/captures/processor.py` (`30e1d8d`):
  - removeu o fallback que usava a primeira foto como `label_image`;
  - adicionou `subprocess.run` com `asyncio.to_thread` para rodar Blender sem `NotImplementedError` no Windows;
  - manteve `PYTHONIOENCODING=utf-8` para reduzir problemas de encoding nos logs.

- `app/modules/captures/service.py` (`30e1d8d`):
  - passou a receber `classifier` e `color_detector` no construtor;
  - executa classificação e detecção de cor em modo gracioso;
  - popula `ProcessingInput.template_id` e `ProcessingInput.liquid_color`;
  - em caso de falha do classificador/detector, não derruba o job.

- `app/main.py` (`30e1d8d`):
  - adicionou factories `build_classifier()` e `build_color_detector()`;
  - loga `processor`, `classifier` e `color` no startup;
  - expõe `/templates/` para inspeção HTTP dos GLBs normalizados.

- `.env.example` (`30e1d8d`):
  - documenta `CLASSIFIER_TYPE`, `CLIP_MODEL`, `DEFAULT_TEMPLATE_ID` e `COLOR_DETECTOR_TYPE`.

- `storage/model_viewer.html` (`338d935`):
  - viewer local com `@google/model-viewer`, `camera-controls` e `auto-rotate`;
  - agrupa templates puros, candidatos customizados e saídas reais para comparação visual.

- `scripts/build_feeling_label.py`, `scripts/blender/generate_feeling_template.py`, `scripts/blender/preview_feeling_template.py` (`5a7663d`):
  - geram label PNG dourada;
  - constroem geometria procedural no Blender com corpo azul/preto, tampa escura e label vertical;
  - exportam `assets/templates/normalized/feeling_rectangular_blue.glb`;
  - geram previews PNG para inspeção fora do app.

### 4.2 Frontend

- `lib/core/constants/app_constants.dart` (`91eaaaa`, `f0537cb`):
  - ajusta URL base do backend para desenvolvimento local em rede.

- `android/app/src/main/AndroidManifest.xml` (`f0537cb`):
  - adiciona permissão `INTERNET`;
  - habilita `android:usesCleartextTraffic="true"` para URLs HTTP locais.

- `lib/features/processing/presentation/pages/processing_status_page.dart` (`f0537cb`):
  - troca "Tentar novamente" por "Revisar e reenviar";
  - reseta o controller de processamento;
  - navega para a revisão/captura em vez de insistir no mesmo `jobId`.

- `lib/features/product_capture/presentation/state/capture_state.dart` (`f0537cb`):
  - adiciona `selectingFromGallery`.

- `lib/features/product_capture/presentation/state/capture_controller.dart` (`f0537cb`):
  - centraliza adição de múltiplos arquivos com limite `maxImages`;
  - impede segunda chamada ao picker enquanto a anterior está ativa;
  - trata `PlatformException(already_active)` com mensagem específica;
  - adiciona `recoverLostGallerySelection()` via `ImagePicker.retrieveLostData()`.

- `lib/features/product_capture/presentation/pages/capture_camera_page.dart` (`f0537cb`):
  - pausa o stream da câmera antes de abrir a galeria;
  - muda o botão para "Abrindo..." enquanto o picker está ativo;
  - navega automaticamente para revisão quando imagens são recuperadas/adicionadas.

### 4.3 Dependências

Não há evidência de novo pacote Flutter introduzido especificamente nesta sessão; portanto, `flutter pub get` não era necessário para essas correções. As mudanças Android foram de manifesto/permissões.

No backend, as dependências pesadas já eram parte da Fase 2:

- `requirements-classifier.txt`: `torch`, `transformers`, `pillow`.
- `requirements.txt`: FastAPI, SQLAlchemy async, `httpx`, etc.

O uso de `@google/model-viewer` no `storage/model_viewer.html` depende de CDN no navegador, mas não altera `requirements.txt`.

## 5. Problemas encontrados e soluções

### 5.1 Falha no envio: `No route to host`

Sintoma no app: `AppException: Falha ao enviar imagens: The connection errored: No route to host`.

Diagnóstico: o celular não alcançava o endereço configurado para o backend. A causa provável foi IP local desatualizado ou confusão entre `localhost` do celular e notebook.

Solução: confirmar que backend estava em `0.0.0.0:8000`, validar `/health` pelo notebook e ajustar o IP usado pelo Flutter para o IPv4 da interface Wi-Fi do notebook. Commit associado no front: `91eaaaa`.

### 5.2 Blender falhando com `NotImplementedError` no Windows

Sintoma no backend: stack trace em `asyncio.create_subprocess_exec`, dentro de `TemplateProcessor._run_blender`.

Tentativa descartada: insistir em subprocess assíncrono nativo, dependente do event loop ativo no Windows.

Solução final: executar `subprocess.run` em thread via `asyncio.to_thread`, mantendo timeout e captura de stdout/stderr. Commit associado: `30e1d8d`.

### 5.3 Retry reaproveitando job terminal

Sintoma: após erro, o app continuava emitindo `GET /captures/<id>/status` para o mesmo job, sem criar novo processamento.

Solução: o botão passou a levar o usuário para revisar e reenviar, criando novo job no próximo upload. Commit associado: `f0537cb`.

### 5.4 WebView Android bloqueando HTTP local

Sintoma: tela "Página da Web não disponível" com `net::ERR_CLEARTEXT_NOT_PERMITTED`.

Solução: adicionar permissão de internet e permitir cleartext no manifesto Android para o MVP local. Commit associado: `f0537cb`.

### 5.5 Resultado visual muito diferente do perfume real

Sintoma: o modelo gerado parecia frasco quadrado/alaranjado ou genérico, enquanto a foto real mostrava frasco retangular alto, azul-escuro, tampa preta e texto dourado vertical.

Diagnóstico:

- a classificação CLIP estava limitada pelos templates disponíveis e pela leitura das imagens;
- o detector de cor por média era sensível a fundo branco e tampa preta;
- a aplicação automática da foto inteira como label gerava artefatos;
- o catálogo não tinha um template fiel ao perfume Hinode Feelin' Flame.

Soluções adotadas nesta linha de trabalho:

- remover auto-label por primeira foto (`30e1d8d`);
- manter filtro cromático no `AverageColorDetector` como mitigação parcial (`1d4ec12`);
- criar viewer local para comparar saídas sem o celular (`338d935`);
- criar template procedural `feeling_rectangular_blue` (`5a7663d`).

### 5.6 Galeria travando com `already_active`

Sintoma: o usuário selecionava várias fotos da galeria, nada acontecia, e na nova tentativa aparecia `PlatformException(already_active, Image picker is already active)`.

Diagnóstico: o picker estava sendo tratado como operação reentrante, enquanto o plugin Android exige que uma seleção esteja concluída antes da próxima chamada.

Solução: estado `selectingFromGallery`, botão desabilitado, pausa do stream da câmera e recuperação com `retrieveLostData()`. Commit associado: `f0537cb`.

### 5.7 Divergência documental sobre `feeling_rectangular_blue`

Os documentos posteriores registram a pendência "GLB para `feeling_rectangular_blue`" como não atendida ou menos crítica. O Git, porém, mostra que `5a7663d` adicionou `assets/templates/normalized/feeling_rectangular_blue.glb` em 2026-04-26.

Por regra metodológica deste histórico, o Git tem prioridade. A pendência deve ser considerada cumprida nesta sessão para o pipeline de templates, ainda que a trilha IA posterior reduza a importância desse template específico.

## 6. Conceitos teóricos envolvidos

- **Validação ponta a ponta.** A sessão demonstra que testes unitários verdes não garantem usabilidade do sistema integrado. Rede, SO, permissões mobile, codecs, WebView e tempo de processamento compõem a validade operacional do MVP.
- **Arquitetura plugável por interfaces.** `Processor`, `Classifier` e `ColorDetector` funcionam como contratos que permitem fallback, bypass e troca de implementação sem alterar as rotas HTTP.
- **Zero-shot image-text classification.** O CLIP compara embeddings de imagem e texto; sua qualidade depende fortemente da cobertura textual dos candidatos e da representatividade das imagens de entrada.
- **Estatística robusta simples para cor.** A filtragem de pixels cromáticos antes da média reduz influência de fundo neutro, mas não resolve todos os casos com reflexo, tampa escura ou frasco transparente.
- **Orientação EXIF e pré-processamento.** Fotos de celular podem armazenar orientação em metadados, não na matriz de pixels. Ignorar EXIF altera o que classificadores e detectores "veem".
- **Event loop e offloading de bloqueio.** `asyncio.to_thread` é um compromisso prático para integrar tarefas bloqueantes ou dependentes de subprocess em aplicações assíncronas.
- **Modelo de segurança Android para cleartext.** A plataforma bloqueia HTTP sem TLS por padrão em versões modernas; liberar cleartext é aceitável apenas em ambiente local controlado.
- **Estado assíncrono em UI mobile.** Operações modais como image picker exigem guarda contra reentrância e recuperação de estado quando o processo Android é suspenso.
- **Visualização 3D como ferramenta de diagnóstico.** Um viewer isolado separa problemas de geração GLB de problemas de app, reduzindo variáveis durante a depuração.

## 7. Pendências e próximos passos

### 7.1 Pendências anteriores revisitadas

Fonte principal: `historico/2026-04-26_fase2-templates-clip-cor.md`, seção 7.2.

| Pendência anterior | Estado nesta sessão |
|---|---|
| 7.2.1 Qualidade da classificação CLIP em casos reais. | 🔄 **Parcialmente mitigada.** O caso Hinode foi tratado pela criação do template `feeling_rectangular_blue` (`5a7663d`), mas o problema geral de avaliação CLIP em lote diverso continua pendente. |
| 7.2.2 Segmentação de label. | 🔄 **Modificada.** Em vez de usar a foto inteira como label, o fallback foi removido (`30e1d8d`). A extração real da label permanece pendente neste ponto da cronologia; documentos posteriores tratam `LabelExtractor`, `LabelUpscaler` e `LabelProjector`. |
| 7.2.3 GLB para `feeling_rectangular_blue`. | ✅ **Cumprida nesta sessão.** O Git registra `assets/templates/normalized/feeling_rectangular_blue.glb` em `5a7663d`. Há divergência com textos posteriores que mantiveram essa pendência como não atendida; prevalece o Git. |
| 7.2.4 Build GPU do PyTorch. | ⏳ **Ainda pendente.** O CLIP no host continua dependente da instalação local de PyTorch; a sessão não mudou build CPU/GPU. |
| 7.2.5 Cor neutra para frascos brancos/transparentes. | ⏳ **Ainda pendente.** O filtro cromático melhora o caso azul do Hinode, mas não cria uma heurística específica para frascos brancos/transparentes. |

As pendências dos documentos `2026-05-09_pipeline-ia-segmentacao-e-refinamento.md` e `2026-04-28_fase4-fase5-preprocessamento-cleanup-label.md` não são "anteriores" a esta sessão pela cronologia Git; elas pertencem a trabalhos de 2026-04-27 em diante. Foram lidas para consistência, mas não são herdadas por esta sessão.

### 7.2 Novas pendências geradas por esta sessão

1. **Configuração de backend no app por ambiente.** Evitar IP hardcoded em `app_constants.dart`; usar flavor, `--dart-define` ou tela/config local para alternar backend.
2. **Cleartext dev-only.** Migrar `android:usesCleartextTraffic="true"` para configuração restrita de debug ou `network_security_config`, evitando levar a exceção para release.
3. **Persistir metadados de processamento.** Salvar `template_id`, confiança CLIP, `liquid_color` e versão do processor no job facilitaria auditoria acadêmica e comparação de resultados.
4. **Benchmark visual de templates.** Criar conjunto pequeno de perfumes reais e registrar, por foto, template escolhido, cor detectada e render final.
5. **Critério objetivo para "parecido".** Definir métrica de aceitação para o TCC: por exemplo, avaliação humana cega, escala Likert, ou comparação de atributos discretos (forma, cor, tampa, label).
6. **Fluxo de inspeção notebook como ferramenta formal.** Incorporar o `model_viewer.html` ao roteiro de validação, com pasta de artefatos e screenshots versionados quando apropriado.
7. **Consolidar divergências dos históricos posteriores.** Revisar menções futuras a `feeling_rectangular_blue` como "sem GLB", pois o commit `5a7663d` contradiz essa afirmação.

## 8. Reflexão para o TCC

Esta sessão é metodologicamente importante porque desloca o projeto de "pipeline implementado" para "pipeline exercitado no ambiente real". A diferença apareceu em problemas que não seriam capturados por testes unitários: IP de rede local, permissão Android, event loop Windows, semântica de retry, reentrância do picker e percepção visual do modelo.

Também fica claro que a validação empírica corrigiu o rumo técnico. O pipeline de templates era coerente, mas o teste com um perfume real mostrou limites de generalização. A resposta imediata foi pragmática: corrigir os gargalos de integração e criar um template procedural mais fiel. A resposta de médio prazo, documentada em sessões posteriores, foi abrir caminho para geração 3D por IA.

Para o artigo futuro, esta sessão pode sustentar uma discussão sobre prototipagem incremental: primeiro cria-se uma arquitetura simples e testável; depois, o contato com dados reais expõe onde heurísticas e templates deixam de ser suficientes. Esse ciclo é mais defensável academicamente quando fica ancorado em commits, logs, imagens de entrada e artefatos GLB inspecionáveis.
