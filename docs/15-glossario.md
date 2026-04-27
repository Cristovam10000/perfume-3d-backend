# 15 — Glossário

| Termo | Significado no projeto |
|-------|------------------------|
| **GLB** | Formato glTF 2.0 binário; único ficheiro com geometria, materiais e texturas embutidas. Saída do pipeline 3D. |
| **Template (3D)** | Ficheiro `.glb` em `assets/templates/normalized/`, com convenção de nós (Bottle, Cap, …) e materiais conhecidos pelo `customize_template.py`. |
| **Template ID** | Nome do ficheiro sem extensão, ex.: `feeling_rectangular_blue`. O classificador devolve isso; o `TemplateProcessor` abre o GLB correspondente. |
| **Processor** | Estratégia que gera o modelo final: cubo falso, ou Blender a partir de template. |
| **FakeProcessor** | Gera GLB mínimo (cubo) sem Blender; usado com `PROCESSOR_TYPE=fake`. |
| **TemplateProcessor** | Invoca Blender com `customize_template.py` e exporta o GLB do job. |
| **Classifier** | Escolhe o `template_id` com base nas fotos (CLIP) ou fica desligado (`disabled`). |
| **Color detector** | Infere a cor do líquido em `#RRGGBB` a partir do crop central das imagens (Pillow) ou fica `disabled`. |
| **Job** | Unidade de trabalho: um UUID, N fotos, estados e eventualmente o caminho do modelo. |
| **ProcessingInput** | Dados passados do service ao `Processor` (paths, `template_id`, `liquid_color`, etc.). |
| **modelUrl** | URL absoluta devolvida no status, apontando para `/files/models/<id>.glb` no mesmo host. |
| **Lifespan** | Ganchos de startup/shutdown do FastAPI; aqui: criar tabelas, subir fila, injetar serviço. |
| **Normalize (template)** | Processo *offline* no Blender: converter raw Sketchfab em GLB com nós e escala padrão. |
| **Procedural (Feelin' Flame)** | Script offline que gera o template `feeling_rectangular_blue` sem ser fotogrametria. |

## Leituras relacionadas

- [01 — Visão geral](01-visao-geral.md)
- [09 — Pipeline 3D](09-pipeline-3d.md)
