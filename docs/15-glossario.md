# 15 — Glossário

## Pipeline 3D

| Termo | Significado no projeto |
|-------|------------------------|
| **GLB** | Formato glTF 2.0 binário; único ficheiro com geometria, materiais e texturas embutidas. Saída do pipeline 3D. |
| **Pipeline integrado** | A composição `IntegratedPipeline` que executa preprocess → rembg → cache → Hunyuan → cleaner → refiner → label → store dentro do worker do `CaptureService`. Caminho default do backend. Ver [09f](09f-pipeline-integrado.md). |
| **Stage** | Cada etapa do `IntegratedPipeline`. Cada stage é uma ABC com `Disabled*` e implementação real. |
| **Processor** | ABC raiz que `IntegratedPipeline`, `TemplateProcessor` e `FakeProcessor` implementam. Trocar entre eles é uma decisão de `PIPELINE_MODE` no `.env`. |
| **FakeProcessor** | Gera GLB mínimo (cubo) sem Blender; usado com `PIPELINE_MODE=fake`. |
| **TemplateProcessor** | Invoca Blender com `customize_template.py` em cima de um GLB pré-existente. Hoje é caminho de **fallback** quando o Hunyuan está offline. |
| **Hunyuan3DProcessor** | Cliente HTTP do contêiner Docker Hunyuan3D-2mv. Stage (4) do pipeline integrado. |
| **Template (3D)** | Ficheiro `.glb` em `assets/templates/normalized/`, com convenção de nós (Bottle, Cap, Liquid, Label) e materiais conhecidos pelo `customize_template.py`. |
| **Template ID** | Nome do ficheiro sem extensão, ex.: `feeling_rectangular_blue`. Usado no caminho de fallback. |
| **Normalize (template)** | Processo *offline* no Blender: converter raw Sketchfab em GLB com nós e escala padrão. |
| **Procedural (Feelin' Flame)** | Script offline que gera o template `feeling_rectangular_blue` sem ser fotogrametria. |

## Cache de modelos

| Termo | Significado |
|-------|------------------------|
| **ModelCache** | ABC do cache. Tem `lookup(embedding)` e `store(embedding, glb, meta)`. Implementação real é `ClipSimilarityCache`. Ver [09g](09g-cache-similaridade-clip.md). |
| **Embedding (CLIP)** | Vetor 512-d (L2-normalizado) que representa o conjunto de fotos de um job. Calculado pelo `ClipImageEmbedder` como mean-pool dos embeddings de cada foto. |
| **Mean-pool** | Operação simples de tirar a média de N vetores → 1 vetor. Forma deliberadamente ingênua de agregar várias vistas; suficiente para o MVP. |
| **L2-normalize** | Dividir o vetor pela sua norma euclidiana. Após normalização, **cosine similarity vira produto interno** (dot product), o que simplifica e acelera a busca. |
| **Cosine similarity** | Métrica de proximidade entre vetores no intervalo [-1, 1]. Vetores idênticos têm 1.0; ortogonais 0.0. Robusta a magnitude (que é o que queremos — duas fotos do mesmo perfume com luzes diferentes podem ter magnitude diferente mas direção igual). |
| **Threshold de similaridade** | Valor de cosine acima do qual o cache responde "hit". Default proposto 0.92; precisa de calibração com dataset real. `CACHE_SIMILARITY_THRESHOLD` no `.env`. |
| **Cache hit** | Um job cujo embedding bate (cosine ≥ threshold) com uma entrada de `modelos_3d_universais`. O backend devolve o GLB cacheado em segundos sem chamar o Hunyuan. |
| **Cache miss** | Nenhuma entrada bate. O pipeline segue para Hunyuan + pós-proc + `store` no cache no fim. |
| **Cold start** | Estado inicial com `modelos_3d_universais` vazia. Todos os jobs viram miss até a primeira geração concluir e popular a tabela. Esperado. |
| **`modelos_3d_universais`** | Tabela Postgres com o **cache global** de moldes 3D (id, caminho_arquivo_modelo, embedding bytes, source_job_id, hit_count, ultimo_hit_em). Sem FK para produtos — compartilhada cross-tenant. Ver [12](12-armazenamento-e-banco.md). |
| **`modelos_3d_produto`** | Tabela Postgres **existente** que amarra produto comercial (do `/sales`) a um GLB. `produto_id UNIQUE`. Ganha coluna `modelo_universal_id` (FK opcional para `modelos_3d_universais`) na integração do pipeline. Permite que vários produtos de tenants diferentes apontem para o mesmo molde universal. |
| **Molde universal** | Termo informal para uma entrada de `modelos_3d_universais` — o GLB de um frasco específico, identificado pelo embedding visual, compartilhado entre todos os usuários do sistema. |
| **Cross-tenant** | Característica do cache: usuário A gera o molde de um perfume, usuário B fotografa o mesmo perfume depois e reaproveita o GLB do A sem regerar via Hunyuan. Possível porque a chave do cache é o embedding visual, não o `produto_id` (que é por tenant). |

## Componentes auxiliares

| Termo | Significado |
|-------|------------------------|
| **ImageEmbedder** | ABC do componente que produz `ImageEmbedding` a partir de N fotos. Implementação real é `ClipImageEmbedder`. |
| **CLIP zero-shot** | Uso do CLIP para tarefas que ele não foi explicitamente treinado para fazer (sem fine-tuning). No projeto, hoje é usado **só para embedding**; o uso anterior como classificador de forma foi depreciado. |
| **rembg** | Biblioteca Python que faz remoção de fundo via modelos ONNX (default `isnet-general-use`). Stage (2) do pipeline. |
| **Máscara RGBA** | PNG com canal alpha onde 255 = frasco e 0 = fundo. Saída do `RembgBackgroundRemover`. |
| **Homography** | Transformação de perspectiva (8 graus de liberdade) que mapeia 4 cantos de um quadrilátero em outros 4. Usada pelo `HomographyLabelExtractor` para "achatar" a label inclinada. |
| **Decal (label)** | Aplicação de textura sobre uma região do mesh sem alterar a geometria. O `BlenderLabelProjector` cria um decal planar na face frontal do frasco. |
| **Front axis** | Eixo no espaço do GLB que aponta para a frente do frasco (default `front_y_neg`). Usado pelo `BlenderLabelProjector` para decidir onde aplicar o decal. |
| **PBR (Physically Based Rendering)** | Modelo de renderização que aproxima física real (BRDF, IOR, roughness, etc.). O `BlenderMeshRefiner` aplica vidro PBR no corpo do frasco. |
| **IOR (Index of Refraction)** | Quanto a luz desvia ao entrar no material. Vidro de perfume: ~1.45. |
| **Transmission** | Quanto da luz atravessa o material em vez de refletir. Vidro polido: 1.0. |
| **Marching Cubes (MC)** | Algoritmo clássico de extração de mesh a partir de campo escalar. Usado pelo Hunyuan para sair do espaço latente para geometria. |
| **Dual Marching Cubes (DMC)** | Variante de MC que preserva melhor arestas vivas. No projeto, falhou no container por incompatibilidade da `diso`; default operacional é `mc`. |
| **Octree resolution** | Resolução da grade volumétrica usada pelo Hunyuan. Mais alto = mais detalhe geométrico + mais VRAM. Default 384. |

## Operacional

| Termo | Significado no projeto |
|-------|------------------------|
| **Job** | Unidade de trabalho: um UUID, N fotos, estados (`waiting`, `processing`, `completed`, `error`) e eventualmente o caminho do modelo. |
| **ProcessingInput** | Dataclass passada do service ao `Processor` (paths, `template_id`, `liquid_color`, etc.). |
| **modelUrl** | URL absoluta devolvida no status, apontando para `/files/models/<id>.glb` no mesmo host. |
| **Lifespan** | Ganchos de startup/shutdown do FastAPI; aqui: criar tabelas, subir fila, injetar serviço. |
| **mmgp profile** | Política de offload de pesos do Hunyuan entre VRAM/RAM/disco. Profile 4 é o default seguro para 8GB de VRAM. |

## Histórico

| Termo | Estado | Substituto |
|-------|------------------------|---|
| **Classifier (CLIP zero-shot por descrição)** | Depreciado. Era usado para escolher entre 6 templates por texto. | Embedder CLIP via cache (uso de imagem-vs-imagem). |
| **ColorDetector** | Depreciado do fluxo principal. | Hunyuan infere cor das fotos. |
| **PROCESSOR_TYPE** | Renomeado. | `PIPELINE_MODE` (`fake | template | integrated`). Compatibilidade mantida com warning. |
| **Fotogrametria (Meshroom/COLMAP)** | Descartada. | Hunyuan3D-2mv. Vidro reflexivo violava a premissa de correspondência de pontos. |

## Leituras relacionadas

- [01 — Visão geral](01-visao-geral.md)
- [09f — Pipeline integrado](09f-pipeline-integrado.md)
- [09g — Cache de similaridade CLIP](09g-cache-similaridade-clip.md)
