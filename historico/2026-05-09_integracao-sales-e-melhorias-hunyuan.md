# Sessão 2026-05-09 — Integração comercial, estoque e melhorias operacionais do Hunyuan

## 1. Metadados

- **Título:** Integração comercial do app com backend real e endurecimento operacional do pipeline Hunyuan.
- **Data aproximada:** 2026-05-09, com trecho anterior de preparação em 2026-04-29.
- **Fase do projeto:** transição entre MVP visual 3D e MVP comercial integrado. A sessão é paralela ao pipeline 3D: não substitui as Fases 4-5, mas conecta a experiência de estoque/vendas ao backend e corrige parâmetros do Hunyuan usados em validação.
- **Escopo/objetivo principal:** unir parte do front comercial ao PostgreSQL/FastAPI, substituir parte do estado mock/local por endpoints reais, preservar fallback local no Flutter e ajustar a geração Hunyuan para maior qualidade e melhor diagnóstico de falhas.
- **Posicionamento cronológico inferido:** **sessão 6 documentada**. Pelo Git, vem depois da sessão das Fases 4-5 (`6e6f212`, 2026-04-28) e depois do reforço do smoke Hunyuan (`df843ca`, 2026-04-29). Ela substitui a linha "sem documento — fora do escopo de captures" que existia no `historico/INDEX.md` para o commit `724915c`.
- **Commits Git associados:**
  - `df843ca` — 2026-04-29 — `feat(smoke): enhance Hunyuan3DProcessor with configurable parameters and error handling`. Precursor direto: tornou `smoke_phase5.py` parametrizável para `timeout_seconds`, `octree_resolution` e `num_inference_steps`, além de mensagens melhores de timeout.
  - `724915c` — 2026-05-09 — `feat(sales): introduce sales module with repository, router, and schemas`. Commit principal desta sessão no backend: cria módulo `sales`, registra router no FastAPI, adiciona bootstrap de schema comercial e amplia os parâmetros do `Hunyuan3DProcessor`.
- **Trabalho sem âncora Git dentro desta sessão:**
  - `C:\TCC\front` tem mudanças locais não commitadas em `lib/core/constants/app_constants.dart` e `lib/features/sales/data/sales_repository.dart`.
  - `C:\TCC\docker\hunyuan\server.py`, `Dockerfile`, `README.md` e `C:\TCC\docker-compose.yml` foram ajustados fora do repositório Git `back`; `C:\TCC` não é repositório Git. Portanto, essas mudanças são registradas aqui como evidência de working tree, não como commit.
- **Sessões anteriores referenciadas:**
  - `historico/2026-04-26_preparacao-blender-templates.md`
  - `historico/2026-04-26_fase2-templates-clip-cor.md`
  - `historico/2026-04-26_validacao-e2e-mobile-viewer-local.md`
  - `historico/2026-05-09_pipeline-ia-segmentacao-e-refinamento.md`
  - `historico/2026-04-28_fase4-fase5-preprocessamento-cleanup-label.md`

## 2. Contexto inicial

Antes desta sessão, o backend já tinha dois blocos bem definidos:

1. **Pipeline 3D:** `captures` com `FakeProcessor`, `TemplateProcessor`, `Hunyuan3DProcessor`, pré-processamento de imagem, remoção de fundo, refinamento de malha, limpeza conservadora e aplicação de label por decal. Esse estado está documentado nas sessões das Fases 1-5 do pipeline IA.
2. **Fluxo comercial no front:** o app Flutter já possuía telas de vendas/estoque e `SalesLocalStorage`, mas o estado comercial ainda dependia majoritariamente de mock/localStorage. O commit `front:40a5b5c` de 2026-04-27 já havia introduzido persistência local para vendas, produtos e estoque, mas não havia contrato HTTP real com o backend para o módulo comercial.

O problema que motivou a sessão foi duplo:

- O front precisava deixar de ser apenas protótipo local e passar a buscar dados reais do PostgreSQL: clientes, produtos, estoque, vendas, parcelas, pagamentos e notificações.
- O pipeline Hunyuan, após os smokes reais, precisava de parâmetros mais fortes e de diagnóstico melhor. Em especial, a conversa identificou que `octree_resolution=256` e `num_inference_steps=30` eram conservadores demais para qualidade, enquanto `dmc` falhava no container por incompatibilidade da biblioteca `diso`.

Também houve uma etapa operacional de popular/analisar o banco com dados comerciais reais de clientes e parcelas. Essa carga de dados é relevante para validação do app, mas não aparece como commit; ela deve ser tratada como estado local do PostgreSQL `tcc` no container `tcc-postgres`.

## 3. Decisões arquiteturais e de design

### 3.1 Criar um módulo `sales` separado de `captures`

Opções consideradas implicitamente:

| Opção | Decisão | Justificativa |
|---|---|---|
| Misturar vendas dentro de `captures` | Descartada | `captures` é domínio de geração 3D; vendas/estoque/cobrança têm ciclo de vida e tabelas próprias. |
| Criar módulo comercial separado | Escolhida | Mantém arquitetura feature-first do backend: `modules/captures`, `modules/health`, `modules/sales`. |
| Manter tudo no front/localStorage | Descartada como caminho final | Útil para protótipo offline, mas insuficiente para TCC com persistência real e consultas auditáveis. |

A decisão confirma a arquitetura modular já documentada em `historico/2026-04-26_fase2-templates-clip-cor.md`: cada domínio fica isolado em router, schemas e repositório próprios.

### 3.2 Usar endpoint de snapshot para sincronização inicial do front

Foi escolhido o endpoint:

```text
GET /sales/snapshot
```

Ele retorna em uma única resposta os agregados que o front precisa para montar a tela: clientes, produtos, vendas, parcelas, pagamentos e notificações.

Trade-off:

- **Vantagem:** reduz várias chamadas iniciais, simplifica hidratação do estado Riverpod e combina bem com fallback local.
- **Custo:** o payload pode crescer. Em escala maior seria necessário paginação/cache por entidade, mas para o MVP acadêmico a simplicidade é mais valiosa.

### 3.3 Manter fallback local no Flutter

O front não passou a depender exclusivamente do backend. `SalesController` tenta buscar `/sales/snapshot`, mas se o backend estiver indisponível continua com `localStorage`/mock.

Justificativa: o app ainda é usado em ambiente local, com backend e Docker nem sempre ativos. Manter fallback preserva usabilidade durante apresentação, desenvolvimento e testes sem rede.

### 3.4 Redução automática de estoque no backend ao confirmar venda

A venda passou a ser a operação que reduz estoque de forma transacional no backend:

```sql
update produtos
set estoque = estoque - :quantidade
where id = :produto_id
  and ativo = true
  and estoque >= :quantidade
```

O front já fazia redução local para feedback imediato; a decisão importante foi repetir a regra no servidor, pois estoque é dado de domínio e não pode depender apenas do cliente.

### 3.5 Bootstrap leve de schema em vez de Alembic

O projeto ainda não usa Alembic. Para não recriar banco nem quebrar ambientes locais antigos, foi adotado `ensure_sales_schema(engine)`, que aplica `ALTER TABLE IF EXISTS` para colunas de estoque/cadastro:

- `custo`
- `estoque_minimo`
- `volume_ml`
- `frasco_color_value`

Trade-off: é menos formal que migração versionada, mas é compatível com o estágio atual do pré-projeto. A pendência de Alembic permanece.

### 3.6 Melhorias de qualidade do Hunyuan

Foram adotados parâmetros mais agressivos para geração:

| Parâmetro | Antes | Depois |
|---|---:|---:|
| `timeout_seconds` | 600/900 s | 1200 s |
| `octree_resolution` | 256 | 384 |
| `num_inference_steps` | 30 | 75 |
| `guidance_scale` | implícito | 7.5 |
| `texture_resolution` | implícito/default | 2048 |
| `mc_algo` | tentativa com `dmc` | `mc` como default seguro |

O objetivo foi melhorar forma e textura sem tornar o fluxo completamente inviável na RTX 5050. A decisão por `mc` como default foi técnica: o `dmc` deveria preservar melhor arestas vivas, mas falhou no container com erro de símbolo em `diso/_C.so`.

### 3.7 Checkpoint multi-view e `bf16` no serviço Docker

No serviço Docker fora do Git do backend, o `server.py` foi ajustado para usar:

```python
DEFAULT_SHAPE_SUBFOLDER = "hunyuan3d-dit-v2-mv"
DEFAULT_SHAPE_VARIANT = "bf16"
```

Isso corrige uma limitação importante: apesar do nome Hunyuan3D-2mv, o servidor anterior carregava subfolder single-view. A intenção da mudança é fazer as múltiplas fotos realmente influenciarem a geometria. Como `C:\TCC` não é repositório Git, essa decisão fica registrada como alteração local verificada, não como commit.

### 3.8 Revogação parcial da expectativa sobre `dmc`

Em teoria, Dual Marching Cubes era desejável para frascos retangulares por preservar cantos. Na prática, o container falhou com:

```text
ImportError: Please install diso via `pip install diso`, or set mc_algo to 'mc'
AttributeError: 'NoneType' object has no attribute 'faces'
```

Decisão final: manter `dmc` como opção futura, mas usar `mc` como padrão operacional. Também foi adicionada detecção de malha vazia (`PipelineSemMalhaError`) no `server.py` local para impedir que a textura receba `None`.

## 4. Implementação realizada

### 4.1 Backend comercial (`back`, commit `724915c`)

Arquivos criados:

- `app/modules/sales/__init__.py`
- `app/modules/sales/schemas.py`
- `app/modules/sales/repository.py`
- `app/modules/sales/router.py`

Arquivos modificados:

- `app/main.py`
- `app/modules/captures/processor.py`
- `scripts/smoke_phase3.py`
- `scripts/smoke_phase4.py`
- `scripts/smoke_phase5.py`
- `tests/integration/test_hunyuan_real.py`
- `tests/modules/captures/test_processor.py`

Funcionalidades adicionadas:

- `GET /sales/snapshot`: retorna dados comerciais agregados.
- `POST /sales/products`: cadastra produto com preço, custo, estoque, mínimo, volume e cor.
- `PATCH /sales/products/{product_id}/stock`: repõe ou ajusta estoque.
- `POST /sales/sales`: cria venda, itens, parcelas e reduz estoque.
- `ensure_sales_schema(engine)`: adapta tabelas existentes para campos exigidos pelo front de estoque.

O repositório usa SQL explícito (`sqlalchemy.text`) sobre tabelas já existentes em vez de declarar novos modelos ORM. Isso indica que o banco comercial já tinha estrutura própria e o módulo foi construído como camada de adaptação/API para o front.

### 4.2 Integração front-end (`front`, mudanças locais não commitadas)

Arquivos modificados no repositório `front`:

- `lib/core/constants/app_constants.dart`
- `lib/features/sales/data/sales_repository.dart`

Mudanças principais:

- `backendBaseUrl` deixou de ser IP fixo e passou a aceitar:

```dart
String.fromEnvironment('BACKEND_BASE_URL', defaultValue: 'http://localhost:8000')
```

- `SalesController` passou a criar `Dio` com `AppConstants.backendBaseUrl`.
- Na inicialização, o controller chama `_loadRemote()` e tenta buscar `/sales/snapshot`.
- Cadastro de produto chama `POST /sales/products`.
- Reposição/ajuste de estoque chama `PATCH /sales/products/{id}/stock`.
- Confirmação de venda chama `POST /sales/sales`, desde que cliente/produtos tenham IDs remotos numéricos.
- Os parsers JSON foram relaxados para aceitar IDs vindos como número ou string (`json['id'].toString()`).

Essas mudanças ainda não aparecem em commit no `front` no momento desta documentação.

### 4.3 Melhorias do Hunyuan no backend (`back`, commit `724915c`)

`Hunyuan3DProcessor` passou a enviar mais campos multipart para `/generate`:

```python
dados_form = {
    "octree_resolution": str(self.octree_resolution),
    "num_inference_steps": str(self.num_inference_steps),
    "guidance_scale": str(self.guidance_scale),
    "mc_algo": self.mc_algo,
    "texture_resolution": str(self.texture_resolution),
}
```

Os testes passaram a validar explicitamente esses campos no corpo multipart. Isso é importante academicamente porque transforma a configuração experimental em contrato testável.

### 4.4 Melhorias no serviço Docker Hunyuan (`C:\TCC\docker`, sem Git)

Arquivos ajustados fora do repositório `back`:

- `C:\TCC\docker\hunyuan\server.py`
- `C:\TCC\docker\hunyuan\Dockerfile`
- `C:\TCC\docker\hunyuan\README.md`
- `C:\TCC\docker-compose.yml`

Melhorias específicas verificadas:

- checkpoint de forma default alterado para `hunyuan3d-dit-v2-mv`;
- variante default `bf16`;
- `DEFAULT_MC_ALGO = "mc"`;
- `DEFAULT_OCTREE_RESOLUTION = 384`;
- `DEFAULT_NUM_INFERENCE_STEPS = 75`;
- `DEFAULT_GUIDANCE_SCALE = 7.5`;
- `DEFAULT_TEXTURE_RESOLUTION = 2048`;
- `PipelineSemMalhaError` para detectar lista vazia, `None` ou objeto sem `faces`;
- fallback de forma entre `dmc`, `mc` e octree menor quando aplicável;
- `Dockerfile` passou a incluir `hunyuan3d-dit-v2-mv/*` no `snapshot_download`;
- `docker-compose.yml` recebeu variáveis como `HUNYUAN_SHAPE_SUBFOLDER`, `HUNYUAN_SHAPE_VARIANT`, `HUNYUAN_TEXTURE_MULTI_VIEW` e `MMGP_PROFILE`.

### 4.5 Documento de avaliação do experimento

Na conversa também foi produzido um texto em Markdown para a atividade acadêmica com as seções:

- Resultados;
- Comparação;
- Validação da hipótese;
- Análise crítica;
- Análise de erro;
- Limitações.

O conteúdo comparou `TemplateProcessor`, Meshroom e Hunyuan. A inclusão do Meshroom é importante porque registra o experimento negativo que motivou o pivot para templates e, depois, para IA generativa.

## 5. Problemas encontrados e soluções

### 5.1 Git root não era `C:\TCC`

Ao consultar Git, `C:\TCC` retornou:

```text
fatal: not a git repository
```

O repositório do backend está em:

```text
C:\TCC\back
```

Consequência: arquivos em `C:\TCC\docker` e `C:\TCC\docker-compose.yml` não têm âncora Git. O histórico acadêmico deve registrar essa divergência em vez de fingir que há commit.

### 5.2 `dmc` falhou por incompatibilidade da biblioteca `diso`

Diagnóstico por logs do container Hunyuan:

```text
ImportError: /opt/conda/lib/python3.11/site-packages/diso/_C.so: undefined symbol
ImportError: Please install diso via `pip install diso`, or set mc_algo to 'mc'
```

Depois disso, o pipeline retornou malha `None`, a textura tentou acessar `mesh.faces` e o servidor devolveu HTTP 500.

Solução adotada:

- default operacional alterado para `mc`;
- detecção de malha vazia antes da textura;
- fallback para `mc` quando `dmc` falhar;
- recomendação operacional de rodar smoke com `--mc-algo mc`.

### 5.3 Nome de arquivo com Unicode/descritivo quebrou caminho de imagem

Uma tentativa de smoke usou nomes como:

```text
01_front.jpeg   (a foto 06.03.00 (1) — frente nítida com label).jpeg
```

O preprocessamento gerou nome intermediário, mas a etapa seguinte não encontrou a imagem. A causa provável foi combinação de espaços, parênteses e caractere Unicode em caminho manipulado por OpenCV/Windows.

Solução operacional: renomear as fotos para nomes simples e ASCII:

```text
01_front.jpeg
02_left.jpeg
03_back.jpeg
04_right.jpeg
```

Pendência técnica: sanitizar nomes ou salvar imagens com método tolerante a Unicode no Windows.

### 5.4 Timeout/readiness do Hunyuan

Com parâmetros mais pesados, o Hunyuan demorou mais para ficar pronto ou finalizar `/generate`. O smoke falhou antes com timeout de readiness de 180 s em uma das execuções.

Soluções parciais:

- `timeout_seconds` de geração ampliado para 1200 s;
- mensagens de timeout melhoradas em `df843ca`;
- instrução de acompanhar progresso com `docker compose logs -f --tail=120 hunyuan`;
- validação de readiness via `Invoke-RestMethod http://localhost:7860/health`.

### 5.5 Testes locais bloqueados por permissão em diretório temporário

Ao rodar `pytest`, houve `PermissionError` em diretórios temporários do Windows, inclusive `C:\Users\crish\AppData\Local\Temp\pytest-of-crish` e tentativas em `C:\TCC\tmp`.

O `compileall` passou, e uma importação direta confirmou os defaults do `Hunyuan3DProcessor`:

```text
1200.0 384 75 7.5 mc 2048
```

Pendência: corrigir permissões/limpeza do diretório temporário para voltar a executar a suíte local completa.

### 5.6 Build Docker interrompido e retomado

O rebuild do Hunyuan foi iniciado com:

```powershell
docker compose up -d --build hunyuan
```

O usuário interrompeu uma execução e depois iniciou novamente. A saída mostrou cache nas camadas antigas e execução de:

```text
COPY server.py /app/server.py
RUN python -c "... snapshot_download(...)"
```

Isso indica que o build novo foi iniciado e que a alteração de `server.py` entrou na imagem em construção, mas a conclusão deve ser confirmada por:

```powershell
docker compose exec hunyuan python -c "import server; print(server.DEFAULT_MC_ALGO)"
```

Resultado esperado:

```text
mc
```

## 6. Conceitos teóricos envolvidos

- **Arquitetura feature-first.** Separar `captures` e `sales` evita acoplamento entre geração 3D e operação comercial.
- **Repository Pattern pragmático.** `SalesRepository` centraliza SQL e mapeamento para DTOs, preservando o router sem regra de negócio.
- **DTOs com alias.** Pydantic `Field(serialization_alias=...)` resolve a fronteira Python snake_case ↔ Flutter camelCase.
- **Sincronização offline-first.** O front mantém `localStorage` como fallback, enquanto tenta sincronizar com backend real quando disponível.
- **Transação e invariantes de domínio.** Redução de estoque precisa ocorrer no servidor, junto com a criação da venda, para evitar vendas acima do estoque disponível.
- **Migração incremental sem Alembic.** `ALTER TABLE IF EXISTS` é solução de transição; migrações formais serão necessárias para reproducibilidade científica.
- **Flow matching / image-to-3D.** Aumento de `num_inference_steps` tende a melhorar estabilidade de superfície, com custo linear de tempo.
- **Octree resolution.** Aumentar de 256 para 384 melhora detalhe de geometria, mas aumenta uso de VRAM e tempo de decodificação volumétrica.
- **Marching Cubes vs Dual Marching Cubes.** `dmc` é teoricamente melhor para arestas vivas, mas depende de extensão CUDA funcional. No ambiente atual, `mc` é a opção robusta.
- **Falha de fotogrametria em superfícies especulares.** Meshroom/AliceVision depende de correspondência de pontos estáveis entre fotos; vidro, reflexos e superfícies lisas violam essa premissa.

## 7. Pendências e próximos passos

### 7.1 Pendências anteriores revisitadas

| Pendência anterior | Origem | Estado nesta sessão |
|---|---|---|
| Compor pipeline IA dentro do `CaptureService`. | `historico/2026-05-09_pipeline-ia-segmentacao-e-refinamento.md` §7.2.1 e `historico/2026-04-28_fase4-fase5-preprocessamento-cleanup-label.md` §7.3.2 | ⏳ **Ainda pendente.** Esta sessão mexeu no `Hunyuan3DProcessor` e nos smokes, mas não integrou Hunyuan/preprocess/label ao worker principal de `captures`. |
| Validação visual real do refinador. | `historico/2026-05-09_pipeline-ia-segmentacao-e-refinamento.md` §7.2.2 | 🔄 **Modificada.** Houve novos smokes e análise de falhas, mas a validação formal com relatório visual comparativo ainda não foi concluída. |
| Suite de testes lentos em CI separado. | `historico/2026-05-09_pipeline-ia-segmentacao-e-refinamento.md` §7.2.3 | ⏳ **Ainda pendente.** Os testes com Docker/Blender continuam manuais. |
| Limitações do Hunyuan: vidro, tampa e fundo. | `historico/2026-05-09_pipeline-ia-segmentacao-e-refinamento.md` §7.2.4 | 🔄 **Parcialmente mitigada.** A sessão melhorou parâmetros, checkpoint e fallback, mas não resolveu tampa fundida nem avaliação objetiva de geometria. |
| Caso de borda do refinador sem corpo identificável. | `historico/2026-05-09_pipeline-ia-segmentacao-e-refinamento.md` §7.2.5 | ⏳ **Ainda pendente.** Sem novo teste específico. |
| Avaliação empírica do `LabelExtractor`. | `historico/2026-05-09_pipeline-ia-segmentacao-e-refinamento.md` §7.2.6 | ⏳ **Ainda pendente.** A sessão rodou `--no-label` em parte dos smokes recentes; não houve benchmark de label. |
| Qualidade da classificação CLIP em casos reais. | `historico/2026-04-26_fase2-templates-clip-cor.md` §7.2.1 | ⏳ **Ainda pendente.** A trilha comercial e Hunyuan reduzem a dependência de CLIP, mas não o avaliam. |
| Segmentação de label. | `historico/2026-04-26_fase2-templates-clip-cor.md` §7.2.2 | 🔄 **Já havia sido cumprida em sessões anteriores para o smoke.** Nesta sessão não houve avanço novo; foco foi Hunyuan e sales. |
| Configuração de backend no app por ambiente. | `historico/2026-04-26_validacao-e2e-mobile-viewer-local.md` §7.2.1 | ✅ **Cumprida parcialmente nesta sessão no front local.** `backendBaseUrl` passou a aceitar `--dart-define=BACKEND_BASE_URL=...`, mas a mudança ainda está não commitada no repositório `front`. |
| Persistir metadados de processamento. | `historico/2026-04-26_validacao-e2e-mobile-viewer-local.md` §7.2.3 | ⏳ **Ainda pendente.** O módulo `sales` persiste dados comerciais, mas não metadados do pipeline 3D. |
| Benchmark visual de templates e critério objetivo de "parecido". | `historico/2026-04-26_validacao-e2e-mobile-viewer-local.md` §7.2.4-5 | ⏳ **Ainda pendente.** A atividade de avaliação do experimento registrou métricas de tempo e limitações, mas não criou métrica objetiva de similaridade visual. |
| Migração de dados comerciais reais para backend. | Inferida da conversa desta sessão | ✅ **Cumprida parcialmente.** O banco local foi populado/validado com dados reais de clientes e parcelas; falta transformar isso em seed/migration versionada. |

### 7.2 Novas pendências geradas por esta sessão

1. **Commitar ou documentar separadamente as mudanças do front.** `front` tem alterações locais em `app_constants.dart` e `sales_repository.dart` sem commit.
2. **Versionar o serviço Docker Hunyuan ou criar repositório raiz.** As mudanças em `C:\TCC\docker` e `docker-compose.yml` são centrais para o experimento, mas não têm âncora Git.
3. **Confirmar build aplicado no container.** Rodar `docker compose exec hunyuan python -c "import server; print(server.DEFAULT_MC_ALGO)"` e registrar resultado.
4. **Alinhar `tests/integration/test_hunyuan_real.py`.** O teste lento ainda instancia `mc_algo="dmc"`; decidir se isso será teste opt-in de DMC ou se deve seguir o default `mc`.
5. **Adicionar migrações formais.** Substituir `ensure_sales_schema` por Alembic ou outro mecanismo versionado antes do artigo/TCC final.
6. **Criar seed versionado para dados de demonstração.** Dados de Luciana e Marcos foram úteis para validação, mas precisam virar script reprodutível se forem usados na defesa.
7. **Sanitizar nomes de imagem no smoke.** Evitar falhas com Unicode/espaços em nomes vindos de WhatsApp.
8. **Definir métrica objetiva de qualidade 3D.** A avaliação final deve medir algo além de tempo: taxa de sucesso, avaliação humana, comparação por atributos ou erro de reconstrução aproximado.
9. **Decidir futuro do `dmc`.** Ou corrigir `diso`/CUDA para usar Dual Marching Cubes, ou registrar formalmente que `mc` é o algoritmo suportado no ambiente do TCC.

## 8. Reflexão para o TCC

Esta sessão revela uma mudança importante de maturidade do projeto. Até as sessões anteriores, o foco era provar que era possível gerar e visualizar modelos 3D. Agora o projeto começa a se comportar como um sistema de uso real: há estoque, clientes, vendas, parcelas, persistência em banco, sincronização entre front e backend e regras de domínio como redução automática de estoque.

Ao mesmo tempo, a sessão mostra que o pipeline 3D continua sendo objeto de investigação experimental. A tentativa de usar `dmc` confirma uma hipótese teórica plausível (melhor preservação de quinas), mas o ambiente real impõe uma limitação de dependência CUDA. O resultado metodológico é valioso: nem toda melhoria teoricamente superior é operacionalmente viável no hardware e container disponíveis.

O aprendizado central para o TCC é que o projeto evoluiu para uma arquitetura híbrida em dois sentidos:

1. **Híbrida no produto:** vitrine/estoque/vendas/cobrança conectam a geração 3D a um fluxo comercial concreto.
2. **Híbrida no método:** técnicas clássicas, templates, IA generativa, Docker/GPU e fallback local convivem porque cada uma resolve uma parte diferente do problema.

Também fica explícita uma exigência metodológica para o artigo futuro: diferenciar resultado implementado, resultado validado e resultado apenas configurado. Por exemplo, `mc` está validado como caminho operacional seguro; `dmc` está configurável, mas não validado; front remoto está implementado localmente, mas ainda não commitado; alterações Docker foram aplicadas no working tree, mas sem hash Git. Registrar esses níveis evita inflar conclusões e torna a evolução acadêmica auditável.

---

*Documento gerado em 2026-05-09 a partir da conversa da sessão, inspeção do working tree, leitura dos arquivos em `historico/`, consulta ao Git do backend e ao Git do front. Quando houve divergência entre conteúdo e Git, o Git foi priorizado; mudanças fora de Git foram marcadas explicitamente.*
