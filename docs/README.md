# Documentação técnica — backend `perfume-3d-backend`

Esta pasta descreve o backend FastAPI do repositório `perfume-3d-backend/`. O backend é o serviço HTTP que recebe lotes de fotos do app Flutter, gera um modelo 3D `.glb` por meio de um **pipeline integrado de IA (Hunyuan3D + pós-processamento)** e devolve a URL do modelo pronto. Modelos já gerados de perfumes equivalentes são reaproveitados via **cache por similaridade visual (CLIP)** para evitar regerar o mesmo frasco.

**Conjunto de documentos:** `01-` a `16-` (todos versionados em `docs/`). Quando código e doc divergem, **o código manda** — atualize o Markdown após alterações reais. Os docs marcados como *planejado* descrevem o desenho aprovado para a integração; a implementação acontece em commits subsequentes.

> **Histórico:** versões anteriores deste docs descreveram (a) um pipeline de fotogrametria com Meshroom/AliceVision e (b) um pipeline baseado em **templates Blender** com classificação CLIP. **O caminho de templates foi removido do código em 2026-08** — junto com o fallback, o `MeshCleaner` e o `Classifier` — depois de uma auditoria que mediu o efeito real de cada estágio Blender. Ver [16 - Auditoria do papel do Blender](16-auditoria-blender.md). O sistema comercial (`/sales/*`) é independente do pipeline 3D — ver [13 - Endpoints HTTP](13-endpoints-http.md).

## Ordem sugerida de leitura

1. [01 - Visão geral](01-visao-geral.md): o que o backend faz, fluxo ponta a ponta com cache.
2. [03 - Inicialização do projeto](03-inicializacao-do-projeto.md): como rodar localmente (Postgres + Hunyuan Docker + venv).
3. [05 - Arquitetura](05-arquitetura.md): camadas, Strategy pattern, factories, fluxo do `IntegratedPipeline`.
4. [09f - Pipeline integrado](09f-pipeline-integrado.md): coração do sistema (composição de stages).
5. [09g - Cache de similaridade CLIP](09g-cache-similaridade-clip.md): como o backend evita regerar o mesmo perfume.
6. [13 - Endpoints HTTP](13-endpoints-http.md): contrato com o app Flutter.

## Índice completo

| # | Documento | Assunto |
|---|---|---|
| 01 | [Visão geral](01-visao-geral.md) | O que o backend faz, fluxo, escopo, premissas. |
| 02 | [Stack tecnológico](02-stack-tecnologico.md) | Dependências, versões e papel de cada lib. |
| 03 | [Inicialização do projeto](03-inicializacao-do-projeto.md) | Postgres, venv, `.env`, container Hunyuan, smoke test. |
| 04 | [Estrutura de pastas](04-estrutura-de-pastas.md) | Árvore atual de `app/`, `tests/`, `scripts/`, `assets/`. |
| 05 | [Arquitetura](05-arquitetura.md) | Camadas, Strategy pattern, factories, DI. |
| 06 | [Bootstrap e lifespan](06-bootstrap-e-lifespan.md) | `create_app`, `production_lifespan`, mounts estáticos. |
| 07 | [Camada `core`](07-camada-core.md) | `config`, `database`, `core/exceptions`, `core/logging`, `dependencies`. |
| 08 | [Módulo `captures`](08-modulo-captures.md) | Service, repository, router, models, schemas, queue, pipeline. |
| 09 | [Pipeline 3D — abstração `Processor`](09-pipeline-3d.md) | `Processor` ABC, `FakeProcessor`, e o que aconteceu com o caminho de templates. |
| 09b | [Pipeline IA — Hunyuan3D](09b-pipeline-ai-hunyuan.md) | Cliente HTTP para o serviço Docker, parâmetros, limites. |
| 09c | [Refinamento de malha](09c-refinamento-mesh.md) | Shader de vidro PBR aplicado ao GLB do Hunyuan. |
| 09d | [Pré-processamento de imagem](09d-preprocessamento-e-cleanup.md) | EXIF/WB/CLAHE/resize. O cleanup de malha migrou para o servidor Hunyuan. |
| 09e | [Aplicação de label](09e-aplicacao-label.md) | Extração + upscale + projeção da label real da foto. |
| 09f | [Pipeline integrado](09f-pipeline-integrado.md) | `IntegratedPipeline`: composição dos stages, falhas degradadas, configs. |
| 09g | [Cache de similaridade CLIP](09g-cache-similaridade-clip.md) | `ModelCache`, embeddings, threshold, persistência. |
| 09h | [Segmentação corpo/tampa](09h-segmentacao-corpo-tampa.md) | Separa o mesh único do Hunyuan por pico de densidade de faces. |
| 10 | [Embedder CLIP e detector de cor](10-classificador-e-cor.md) | CLIP como embedder do cache; detector de cor (histórico). |
| 10b | [Segmentação e extração de label](10b-segmentacao-e-label.md) | `RembgBackgroundRemover` e `HomographyLabelExtractor`. |
| 11 | [Templates 3D](11-templates-3d.md) | Catálogo, normalização, geração procedural, atribuições Sketchfab. |
| 12 | [Armazenamento e banco](12-armazenamento-e-banco.md) | `LocalStorage`, schema do Postgres, modelos SQLAlchemy. |
| 13 | [Endpoints HTTP](13-endpoints-http.md) | Contrato HTTP completo (request, response, erros). |
| 14 | [Testes](14-testes.md) | Suíte pytest, fixtures, estratégia de mocks. |
| 15 | [Glossário](15-glossario.md) | Termos do domínio: GLB, template, embedding, cache hit, etc. |
| 16 | [Auditoria do papel do Blender](16-auditoria-blender.md) | Medições do efeito real de cada estágio Blender e as remoções que resultaram. |
| 17 | [Fidelidade do modelo](17-fidelidade-do-modelo.md) | Material declarado pelo app, guarda da foto de topo e projeção do verso real. |

## Convenções

- Todos os caminhos são relativos à raiz do repositório `perfume-3d-backend/`.
- O código Python é a fonte canônica. Quando houver divergência, **atualize os docs** (estão errados, não o código).
- Docs marcados como *planejado* descrevem o design aprovado; código pode estar parcialmente implementado.
- Exemplos de comando assumem PowerShell em Windows. Para bash/zsh, traduza os paths e os ativadores de venv.

## Como manter

Ao modificar uma rota, configuração, módulo ou processo, atualize **pelo menos**:

- [04 - Estrutura de pastas](04-estrutura-de-pastas.md), se a árvore mudar.
- [02 - Stack tecnológico](02-stack-tecnologico.md), se uma dependência for adicionada/removida.
- [05 - Arquitetura](05-arquitetura.md), se uma camada ou Strategy mudar.
- [13 - Endpoints HTTP](13-endpoints-http.md), se a API mudar.
- O documento da feature/módulo afetado.

## Relação com o front

O contrato HTTP entre backend e frontend está em [13 - Endpoints HTTP](13-endpoints-http.md) (`jobId`, `modelUrl` em camelCase, valores de `status`) e no documento correspondente do frontend em [`16-contrato-backend.md`](../../perfume-3d-frontend/docs/16-contrato-backend.md). Mantenha os dois alinhados.

Importante: o frontend **não pré-processa** as fotos além da compressão JPEG (`imageQuality: 90`). EXIF, white-balance, remoção de fundo e segmentação ficam no backend.
