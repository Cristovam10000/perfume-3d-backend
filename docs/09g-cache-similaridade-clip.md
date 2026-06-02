# 09g — Cache de similaridade CLIP (multi-tenant)

> **O que você vai aprender neste doc**
> - Por que regerar o mesmo frasco no Hunyuan é desperdício — e como o **cache CLIP** evita isso.
> - Por que a similaridade usa **embedding CLIP + cosine** (e não `product_id` nem hash perceptual).
> - O modelo de **duas tabelas**: `modelos_3d_universais` (global) × `modelos_3d_produto` (por tenant).
> - Como calibrar o `CACHE_SIMILARITY_THRESHOLD` com dados reais.
>
> **Pré-requisitos:** [09f - Pipeline integrado](09f-pipeline-integrado.md) (quem consome o cache)
> e [12 - Armazenamento e banco](12-armazenamento-e-banco.md) (as tabelas).

## Motivação

O Hunyuan custa caro: 3–8 minutos de GPU por geração. Quando o backend for disponibilizado para múltiplos vendedores, o mesmo perfume vai ser fotografado por gente diferente — a Ana fotografa Empire Sport hoje, o João fotografa o mesmo frasco daqui a um mês. **Regerar o GLB para cada novo vendedor é desperdício de GPU e degrada a experiência do app.**

O cache é o que resolve isso: o backend mantém um **catálogo global de moldes 3D**, identificados pelo embedding visual das fotos que os originaram. Quando chega um job novo, calcula o embedding e procura o vizinho mais parecido. Hit → devolve o GLB em segundos; miss → roda Hunyuan e popula o catálogo.

Importante: o cache é **global por molde de frasco**, não por produto. O `produto_id` da `modelos_3d_produto` é uma chave **por tenant** (cada vendedor tem o próprio catálogo comercial). O molde do frasco, em contraste, é universal — duas linhas diferentes em `produtos` (Empire Sport da Ana e Empire Sport do João) devem apontar para a mesma entrada de `modelos_3d_universais`.

## Por que CLIP (e não product_id manual ou hash perceptual)

| Estratégia | Pró | Contra |
|---|---|---|
| `product_id` do `/sales` | Determinístico, simples | Não funciona cross-tenant: cada vendedor tem o próprio `produto_id`. Mesmo perfume = `product_id` diferente por usuário. Cache não compartilha. |
| Hash perceptual (pHash, dHash) | Rápido, sem ML | Muito sensível a iluminação e ângulo — pequenas variações viram cache miss. Inútil quando dois usuários fotografam o mesmo frasco em locais diferentes. |
| **CLIP embedding + cosine** | Robusto a iluminação e ângulo; CLIP já está no projeto (era usado pelo classificador); cross-tenant por construção | Threshold precisa de calibração; embedding 512-d ocupa ~2KB por entrada; busca linear até ~10k. |

Decidimos pela terceira opção. Foi a escolhida na sessão de design — ver §"Multi-tenant" abaixo.

## Multi-tenant: duas tabelas, papéis distintos

```
┌──────────────────────────────────────────────────────────┐
│ modelos_3d_universais       (cache global, NOVA)         │
│ ───────────────────────────────────────────              │
│ id uuid PK                                               │
│ caminho_arquivo_modelo  text NOT NULL    (storage/cache/)│
│ embedding               bytea NOT NULL   (CLIP 512d)     │
│ embedding_dim           int   NOT NULL   default 512     │
│ source_job_id           varchar          → capture_jobs  │
│ liquid_color            varchar(7)       (metadado opc.) │
│ label_path              text             (audit/debug)   │
│ hit_count               int   NOT NULL   default 0       │
│ ultimo_hit_em           timestamp                        │
│ criado_em               timestamp NOT NULL default now() │
└──────────────────┬───────────────────────────────────────┘
                   │ 1
                   │
                   │ N
┌──────────────────▼───────────────────────────────────────┐
│ modelos_3d_produto       (amarração por tenant, EXISTE)  │
│ ───────────────────────────────────────────              │
│ id bigint PK                                             │
│ produto_id          bigint NOT NULL UNIQUE → produtos    │
│ caminho_arquivo_modelo text NOT NULL   (preservado)      │
│ caminho_imagem_preview text                              │
│ status              varchar(50)                          │
│ capture_job_id      varchar(36) → capture_jobs           │
│ criado_em, atualizado_em                                 │
│ modelo_universal_id uuid NULLABLE → modelos_3d_universais│ ← coluna nova
└──────────────────────────────────────────────────────────┘
```

- **`modelos_3d_universais`** é a tabela nova. Cache global, sem FK para `produtos`. Cada entrada = um molde de frasco identificado por embedding visual.
- **`modelos_3d_produto`** já existe e mantém a semântica "1 modelo por produto do meu catálogo" (a UNIQUE em `produto_id`). Ganha uma coluna nova `modelo_universal_id` que aponta para o cache global. Vários produtos de tenants diferentes podem apontar para o **mesmo molde universal**.

Quando autenticação multi-tenant chegar (com `usuario_id` em `produtos`), **nada na `modelos_3d_universais` precisa mudar** — o cache continua global por construção.

## Fluxo end-to-end com multi-tenant

**Cenário 1 — Ana fotografa Empire Sport (primeira vez):**

1. `POST /captures` com fotos e (opcional) `productId=P_ana`.
2. Pipeline executa preprocess + rembg.
3. `ImageEmbedder` calcula embedding 512-d das fotos.
4. `ModelCache.lookup(embedding)` busca em `modelos_3d_universais` → vazio → **miss**.
5. Hunyuan gera GLB → refiner → label projector → `with_label.glb`.
6. `ModelCache.store(...)`:
   - INSERT em `modelos_3d_universais` (id = `U1`, embedding, caminho do GLB em `storage/cache/U1.glb`, source_job_id, etc.).
   - Se `productId=P_ana` veio na request: UPSERT em `modelos_3d_produto(produto_id=P_ana, modelo_universal_id=U1, caminho_arquivo_modelo=U1.glb, capture_job_id=...)`. A UNIQUE em `produto_id` garante que cadastrar duas vezes só atualiza.
7. Job termina; `modelUrl` aponta para `/files/models/<job_id>.glb` (cópia do GLB cacheado).

**Cenário 2 — João fotografa o mesmo Empire Sport semanas depois:**

1. `POST /captures` com fotos e (opcional) `productId=P_joao`.
2. Pipeline: preprocess + rembg.
3. Embedding bate em `modelos_3d_universais.U1` (cosine ≥ threshold) → **hit**.
4. `ModelCache` copia `storage/cache/U1.glb` → `storage/models/<job_id>.glb` (o GLB do João).
5. Atualiza `U1.hit_count++` e `U1.ultimo_hit_em`.
6. Se `productId=P_joao` veio: UPSERT em `modelos_3d_produto(produto_id=P_joao, modelo_universal_id=U1, ...)`. Agora o produto do João aponta para o mesmo molde universal que o produto da Ana.
7. Stages 4-7 (Hunyuan, refiner, label) **não rodam**. Job conclui em ~8s em vez de ~5min.

**Cenário 3 — Captura órfã (sem produto associado):**

1. `POST /captures` sem `productId` (ou `productId` ausente do form).
2. Pipeline normal. Em miss, popula `modelos_3d_universais` mas **não** cria entrada em `modelos_3d_produto`.
3. O GLB é entregue ao job; o cache continua reutilizável por capturas futuras.
4. Em hit, idem: serve o GLB cacheado, atualiza hit_count, não toca em `modelos_3d_produto`.

## DDL — como o schema é criado

Há **duas fontes** de schema, deliberadamente:

1. A tabela **`modelos_3d_universais` é criada pelo ORM** — `Base.metadata.create_all()` no startup, a partir do mapeamento `ModeloUniversal` em [`modelos_universais.py`](../app/modules/captures/modelos_universais.py).
2. A função **`ensure_captures_schema(engine)`** cuida do que o `create_all()` não toca: a coluna `modelo_universal_id` (+FK) em `modelos_3d_produto` (tabela pré-existente), além de `product_id` em `capture_jobs` e `view` em `capture_images`. Mesmo padrão do `ensure_sales_schema`. É idempotente.

Equivalente DDL (a tabela, gerada pelo ORM; os ALTER, por `ensure_captures_schema`):

```sql
-- (1) Cache global de moldes — gerado pelo ORM (create_all)
CREATE TABLE IF NOT EXISTS modelos_3d_universais (
    id                     varchar(36)  PRIMARY KEY,
    caminho_arquivo_modelo text         NOT NULL,
    embedding              bytea        NOT NULL,
    embedding_dim          int          NOT NULL DEFAULT 512,
    source_job_id          varchar(36),
    liquid_color           varchar(7),
    label_path             text,
    hit_count              int          NOT NULL DEFAULT 0,
    ultimo_hit_em          timestamptz,
    criado_em              timestamptz  NOT NULL DEFAULT now()
);

-- (2) Coluna nova em modelos_3d_produto (tabela já existente) — via ensure_captures_schema
ALTER TABLE IF EXISTS modelos_3d_produto
    ADD COLUMN IF NOT EXISTS modelo_universal_id varchar(36);

-- FK adicionada com guarda: Postgres NÃO tem "ADD CONSTRAINT IF NOT EXISTS",
-- então o código checa information_schema antes (bloco DO $$).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'modelos_3d_produto'
          AND constraint_name = 'fk_modelos_3d_produto_universal'
    ) THEN
        ALTER TABLE modelos_3d_produto
            ADD CONSTRAINT fk_modelos_3d_produto_universal
            FOREIGN KEY (modelo_universal_id)
            REFERENCES modelos_3d_universais(id) ON DELETE SET NULL;
    END IF;
END$$;

CREATE INDEX IF NOT EXISTS idx_modelos_3d_produto_universal
    ON modelos_3d_produto(modelo_universal_id);
```

Nota: a UNIQUE em `produto_id` de `modelos_3d_produto` é preservada. O `ON DELETE SET NULL` garante que excluir um molde do cache não derruba o vínculo do produto comercial — só zera a referência.

## Embeddings

### `ImageEmbedder`

Nova ABC em `app/modules/captures/embeddings.py`:

```python
@dataclass(frozen=True)
class ImageEmbedding:
    vector: np.ndarray  # shape (D,), float32, L2-normalizado
    dim: int            # tipicamente 512 (CLIP ViT-B/32)
    source_paths: list[Path]

class ImageEmbedder(ABC):
    @abstractmethod
    async def embed(self, image_paths: list[Path]) -> ImageEmbedding: ...
```

### `ClipImageEmbedder`

Implementação real. Reutiliza `CLIPModel`/`CLIPProcessor` do HuggingFace já configurados pelo classificador legado. Lógica:

1. Para cada imagem em `image_paths`, abre via PIL, corrige EXIF, passa pelo `image_processor` do CLIP.
2. Roda o `vision_model` (forward) → vetor 512-d por imagem.
3. **Mean-pool**: tira a média dos vetores → 1 vetor de 512.
4. **L2-normalize**: divide pelo norm → vetor unitário (cosine vira simples produto interno).
5. Retorna `ImageEmbedding(vector=..., dim=512, source_paths=image_paths)`.

Modelo configurável via `CACHE_EMBEDDING_MODEL` no `.env`. Default: `openai/clip-vit-base-patch32` — o mesmo que o classificador legado usava.

A inferência roda em `asyncio.to_thread` para não bloquear o event loop.

### `DisabledEmbedder`

Bypass para testes: retorna `ImageEmbedding(vector=np.zeros(512), ...)`. Combinado com `DisabledModelCache`, desliga o cache inteiro sem precisar de torch.

## Cache

### `ModelCache`

ABC em `app/modules/captures/cache.py`:

```python
@dataclass(frozen=True)
class CacheHit:
    universal_id: str
    glb_path: Path
    similarity: float
    hit_count: int

class ModelCache(ABC):
    @abstractmethod
    async def lookup(self, embedding: ImageEmbedding) -> CacheHit | None: ...

    @abstractmethod
    async def store(
        self,
        embedding: ImageEmbedding,
        glb_path: Path,
        *,
        source_job_id: str,
        product_id: int | None = None,
        label_path: Path | None = None,
        liquid_color: str | None = None,
    ) -> str: ...
```

A assinatura do `store` recebe `product_id` opcional — quando vier, o cache amarra `modelos_3d_produto` via UPSERT na mesma transação. Quando não vier, só popula `modelos_3d_universais`.

### `ClipSimilarityCache`

Implementação real. Operações:

**`lookup(embedding)`**:
1. `SELECT id, caminho_arquivo_modelo, embedding, embedding_dim FROM modelos_3d_universais` (todas as entradas).
2. Para cada entrada, desserializa o `embedding` (bytes → np.ndarray 512 floats).
3. Calcula cosine via produto interno (ambos vetores já normalizados).
4. Encontra o máximo. Se `max_sim >= threshold`, retorna `CacheHit(...)`. Senão `None`.
5. No `CacheHit`, faz `UPDATE modelos_3d_universais SET hit_count = hit_count + 1, ultimo_hit_em = now() WHERE id = ?`.

**`store(embedding, glb_path, meta)`**:
1. Gera `universal_id = uuid4()`.
2. Copia `glb_path` para `storage/cache/<universal_id>.glb` via `LocalStorage.cache_path`.
3. Serializa `embedding.vector.tobytes()` → bytes.
4. `INSERT INTO modelos_3d_universais (id, caminho_arquivo_modelo, embedding, ...) VALUES (...)`.
5. Se `product_id is not None`:
   ```sql
   INSERT INTO modelos_3d_produto (produto_id, caminho_arquivo_modelo, status, capture_job_id, modelo_universal_id)
   VALUES (:product_id, :glb_path, 'completo', :source_job_id, :universal_id)
   ON CONFLICT (produto_id) DO UPDATE
       SET modelo_universal_id = EXCLUDED.modelo_universal_id,
           caminho_arquivo_modelo = EXCLUDED.caminho_arquivo_modelo,
           capture_job_id = EXCLUDED.capture_job_id,
           atualizado_em = CURRENT_TIMESTAMP;
   ```
6. Retorna `universal_id`.

### `DisabledModelCache`

Bypass: `lookup` sempre retorna `None`; `store` é no-op. Útil para testes e para desligar o cache temporariamente sem mexer no código (`CACHE_ENABLED=false` no `.env`).

## Threshold

`CACHE_SIMILARITY_THRESHOLD` controla a sensibilidade do cache.

| Threshold | Comportamento |
|---|---|
| 0.99 | Hit só quando as fotos são quase idênticas (mesmo ângulo, mesma iluminação). Quase sempre miss; cache praticamente inútil. |
| 0.95 | Conservador: mesmo perfume com fotos similares casa. Diferentes perfumes do mesmo formato (Empire Sport vs Empire Gold) provavelmente missam. |
| 0.92 | **Default atual** (`config.py`). Equilíbrio entre hit rate e falso-positivo. |
| 0.85 | Permissivo: pode confundir frascos retangulares parecidos. Não recomendado sem calibração. |

CLIP zero-shot não foi treinado para distinguir entre perfumes específicos; é treinado em descrições gerais. Frascos retangulares com labels diferentes podem ter cosine similarity > 0.95 mesmo sendo perfumes distintos. **O threshold inicial 0.92 precisa de calibração com dataset real** antes da defesa do TCC.

Plano de calibração (futuro):
1. Coletar 5–10 fotos de cada um dos perfumes do estoque, tirando em condições variadas (iluminação, ângulo, fundo) para simular fotos de usuários diferentes.
2. Computar embeddings 2-a-2 → matriz de similaridade.
3. Plotar histograma de similaridades intra-produto vs inter-produto.
4. Escolher threshold como o ponto que minimiza falso-positivo + falso-negativo (intersecção das curvas).

## Storage

Layout no disco:

```
storage/
├── uploads/<job_id>/*.jpg     # fotos cruas (curto prazo, podem ser limpas)
├── models/<job_id>.glb        # output do job (cópia do cache em hit, ou GLB recém-gerado em miss)
└── cache/<universal_id>.glb   # GLB cacheado, referenciado por modelos_3d_universais.caminho_arquivo_modelo
```

`LocalStorage.cache_path(universal_id) → Path` é o helper que o `ClipSimilarityCache` usa para gravar/ler.

Quando um job é concluído via cache HIT, o `IntegratedPipeline`:
1. Resolve `cached.caminho_arquivo_modelo` → caminho absoluto em `storage/cache/<universal_id>.glb`.
2. Copia (ou hard-linka, em sistemas que suportam) para `output_path` (= `storage/models/<job_id>.glb`).
3. O `modelUrl` continua sendo `/files/models/<job_id>.glb`. O cache é invisível para o front.

## Endpoints admin (futuros, não MVP)

Planejados para uma sessão futura:

```
GET    /captures/cache             → lista entradas (id, criado_em, hit_count, glb_url)
GET    /captures/cache/<id>         → detalhe (inclui produtos que apontam para esta entrada)
DELETE /captures/cache/<id>         → remove entrada + GLB do disco; ON DELETE SET NULL preserva modelos_3d_produto
```

Útil para curadoria manual quando o threshold der falsos positivos. Como `modelos_3d_produto.modelo_universal_id` é `ON DELETE SET NULL`, apagar um molde do cache não deleta produtos — só desfaz o vínculo, e o produto continua tendo `caminho_arquivo_modelo` (cópia local).

## Falhas e degrade

| Cenário | Comportamento |
|---|---|
| Banco indisponível durante `lookup` | Loga warning; retorna `None` (trata como miss). O job segue para o Hunyuan. |
| Banco indisponível durante `store` | Loga warning; **não** falha o job. O GLB já está no `output_path` e o `modelUrl` será respondido normalmente. Cache simplesmente não foi populado. |
| GLB cacheado sumiu do disco (arquivo deletado manualmente) | Loga erro; trata como miss (regenera via Hunyuan). Não remove a entrada da tabela automaticamente — fica para o endpoint admin de garbage collect. |
| Embedding corrupto (`embedding_dim` ≠ esperado) | Pula essa entrada na busca; loga warning. |
| Cold start (tabela vazia) | Toda chamada vira miss. Esperado e ok — após N gerações o cache começa a render. |
| `productId` veio mas produto não existe | UPSERT em `modelos_3d_produto` falha (FK violation); cache ainda populou `modelos_3d_universais`. Loga warning; job conclui normalmente. |

## Performance

- **Lookup**: O(N · D) — N entradas, D = 512 floats. Para N = 1.000, 1.000 × 512 = 512.000 ops por consulta, < 5 ms em Python com numpy vetorizado.
- **Memória**: 512 floats × 4 bytes = 2KB por entrada. 10.000 entradas = 20MB em RAM. Cabe num processo de backend trivialmente.
- **Storage**: GLB cacheado tipicamente 5–20MB. 10.000 entradas = 50–200GB. Não cabe num disco doméstico sem rotation — política de GC fica para depois.

Acima de 10.000 entradas, a alternativa é trocar `ClipSimilarityCache` por uma implementação com índice (FAISS in-process ou pgvector no Postgres). A ABC `ModelCache` foi desenhada para tornar essa troca local.

## Tabela atualizada de comportamento por origem

| Origem do `POST /captures` | `productId` enviado? | Em cache miss | Em cache hit |
|---|---|---|---|
| Captura iniciada de dentro de um produto do `/sales` | Sim | Gera + popula `modelos_3d_universais` + UPSERT em `modelos_3d_produto` | Serve do cache + UPSERT em `modelos_3d_produto` (vincula o produto deste tenant ao molde) |
| Captura "solta" (sem produto associado) | Não | Gera + popula `modelos_3d_universais` apenas | Serve do cache; sem vínculo com produto |

## Testes

- [`tests/modules/captures/test_embeddings.py`](../tests/modules/captures/test_embeddings.py) (5 testes): valida shape, dimensão, L2 norm; bypass `DisabledEmbedder`.
- [`tests/modules/captures/test_cache.py`](../tests/modules/captures/test_cache.py) (8 testes):
  - `lookup` em tabela vazia → `None`.
  - `store` + `lookup` com mesmo embedding → hit (sim ≈ 1.0).
  - `store` + `lookup` com embedding diferente abaixo do threshold → miss.
  - `lookup` com 100 entradas mock → benchmark < 50ms.
  - `store(product_id=42)` propaga UPSERT em `modelos_3d_produto`.
  - `store(product_id=None)` não toca em `modelos_3d_produto`.
  - Segundo `store` com mesmo `product_id` atualiza `modelo_universal_id` em vez de violar UNIQUE.
  - Hit incrementa `hit_count` e atualiza `ultimo_hit_em`.

## Leituras relacionadas

- [09f — Pipeline integrado](09f-pipeline-integrado.md) (consumidor do cache)
- [09b — Pipeline IA: Hunyuan3D-2mv](09b-pipeline-ai-hunyuan.md) (o que o cache evita repetir)
- [10 — Embedder CLIP e detector de cor](10-classificador-e-cor.md) (`ClipImageEmbedder`)
- [12 — Armazenamento e banco](12-armazenamento-e-banco.md) (DDL completo de `modelos_3d_universais` e alteração de `modelos_3d_produto`)
- [13 — Endpoints HTTP](13-endpoints-http.md) (`POST /captures` com `productId` opcional; endpoints admin futuros)
- [15 — Glossário](15-glossario.md) (embedding, cosine, hit/miss, threshold)
