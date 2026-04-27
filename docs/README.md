# Documentação técnica — backend `perfume-3d-backend`

Esta pasta descreve o estado **atual** do backend FastAPI na raiz `back/`. O backend é o serviço HTTP que recebe lotes de fotos do app Flutter, gera um modelo 3D `.glb` por meio de um pipeline baseado em templates customizados no Blender headless e devolve a URL do modelo pronto.

**Conjunto de documentos:** `01-` a `15-` (todos versionados em `docs/`), alinhados ao código. Se algo divergir, **o código manda** — atualize o Markdown após alterações reais.

> **Importante**: a versão antiga deste docs (`arquiteturamTecnica.md`) descrevia um pipeline de fotogrametria com Meshroom/AliceVision e um sistema comercial/financeiro completo (clientes, vendas, parcelas, pagamentos). **Nada disso existe no backend hoje** — só o pipeline 3D baseado em templates. A doc foi reescrita para refletir só o que está em código.

## Ordem sugerida de leitura

1. [01 - Visão geral](01-visao-geral.md): o que o backend faz, fluxo ponta a ponta.
2. [03 - Inicialização do projeto](03-inicializacao-do-projeto.md): como rodar localmente.
3. [04 - Estrutura de pastas](04-estrutura-de-pastas.md): mapa dos arquivos.
4. [05 - Arquitetura](05-arquitetura.md): camadas, Strategy pattern e factories.
5. [09 - Pipeline 3D](09-pipeline-3d.md): coração do sistema (Processor + Blender).
6. [13 - Endpoints HTTP](13-endpoints-http.md): contrato com o app Flutter.

## Índice completo

| # | Documento | Assunto |
|---|---|---|
| 01 | [Visão geral](01-visao-geral.md) | O que o backend faz, fluxo, escopo, premissas. |
| 02 | [Stack tecnológico](02-stack-tecnologico.md) | Dependências, versões e papel de cada lib. |
| 03 | [Inicialização do projeto](03-inicializacao-do-projeto.md) | Postgres, venv, `.env`, subir o servidor, smoke test. |
| 04 | [Estrutura de pastas](04-estrutura-de-pastas.md) | Árvore atual de `app/`, `tests/`, `scripts/`, `assets/`. |
| 05 | [Arquitetura](05-arquitetura.md) | Camadas, Strategy pattern, factories, DI. |
| 06 | [Bootstrap e lifespan](06-bootstrap-e-lifespan.md) | `create_app`, `production_lifespan`, mounts estáticos. |
| 07 | [Camada `core`](07-camada-core.md) | `config`, `database`, `core/exceptions`, `core/logging`, `dependencies`. |
| 08 | [Módulo `captures`](08-modulo-captures.md) | Service, repository, router, models, schemas, queue, status. |
| 09 | [Pipeline 3D](09-pipeline-3d.md) | `Processor` ABC, `FakeProcessor`, `TemplateProcessor`, `customize_template.py`. |
| 10 | [Classificador e detector de cor](10-classificador-e-cor.md) | CLIP zero-shot e detector de cor do líquido. |
| 11 | [Templates 3D](11-templates-3d.md) | Catálogo, normalização, geração procedural, atribuições Sketchfab. |
| 12 | [Armazenamento e banco](12-armazenamento-e-banco.md) | `LocalStorage`, schema do Postgres, modelos SQLAlchemy. |
| 13 | [Endpoints HTTP](13-endpoints-http.md) | Contrato HTTP completo (request, response, erros). |
| 14 | [Testes](14-testes.md) | Suíte pytest, fixtures, estratégia de mocks. |
| 15 | [Glossário](15-glossario.md) | Termos do domínio: GLB, template, classifier, etc. |

## Convenções

- Todos os caminhos são relativos à raiz `back/`.
- O código Python é a fonte canônica. Quando houver divergência, **atualize os docs** (estão errados, não o código).
- A documentação evita prometer comportamento que ainda não existe — fotogrametria real, autenticação, persistência multi-tenant, observability não estão no escopo atual.
- Exemplos de comando assumem PowerShell em Windows. Para bash/zsh, traduza os paths e os ativadores de venv.

## Como manter

Ao modificar uma rota, configuração, módulo ou processo, atualize **pelo menos**:

- [04 - Estrutura de pastas](04-estrutura-de-pastas.md), se a árvore mudar.
- [02 - Stack tecnológico](02-stack-tecnologico.md), se uma dependência for adicionada/removida.
- [05 - Arquitetura](05-arquitetura.md), se uma camada ou Strategy mudar.
- [13 - Endpoints HTTP](13-endpoints-http.md), se a API mudar.
- O documento da feature/módulo afetado.

## Relação com o front

O contrato HTTP entre back e front está em [13 - Endpoints HTTP](13-endpoints-http.md) (`jobId`, `modelUrl` em camelCase, valores de `status`). Se o repositório Flutter tiver um documento de contrato partilhado (ex. em `front/docs/`), mantenha-o alinhado com a secção 13.
