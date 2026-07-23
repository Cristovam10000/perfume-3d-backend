# Demonstração dos modelos 3D gerados pela IA a partir de fotos reais

## Objetivo

Este arquivo descreve como abrir rapidamente uma galeria local com modelos
`.glb` gerados pelo pipeline de IA a partir de fotos reais de perfumes.

Esta página **não usa** os modelos de avaliação em `TCC_eval_data/outputs/ia`.
Esses modelos pertencem ao conjunto experimental de benchmark. A galeria de
demonstração usa jobs reais presentes em `storage/`.

## URL da galeria

A galeria está em:

```text
C:\TCC\perfume-3d-backend\storage\models\demo-ia\index.html
```

Como o backend FastAPI monta `storage/` em `/files`, ela fica disponível em:

```text
http://localhost:8000/files/models/demo-ia/index.html
```

Em um celular físico na mesma rede Wi-Fi, troque `localhost` pelo IP da máquina:

```text
http://<IP-DO-NOTEBOOK>:8000/files/models/demo-ia/index.html
```

## Como rodar

1. Subir o Postgres:

```powershell
cd C:\TCC\perfume-3d-backend
docker compose up -d postgres
```

2. Subir o backend:

```powershell
cd C:\TCC\perfume-3d-backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

3. Abrir a galeria:

```text
http://localhost:8000/files/models/demo-ia/index.html
```

## Modelos usados na demonstração

Após revisão visual, os melhores resultados locais não são os dois últimos jobs
persistidos no banco (`f522...` e `54db...`). A galeria prioriza os artefatos
que ficaram melhores nos smokes controlados da Fase 3/Fase 5. A Fase 5 está
associada ao perfume preto/dourado, enquanto a Fase 3 está associada ao conjunto
**Empire azul**. A galeria também mantém um job real do `/captures` como exemplo
do fluxo persistido.

Os modelos de smoke foram gerados a partir de fotos reais e ficam copiados para:

```text
C:\TCC\perfume-3d-backend\storage\models\demo-ia
```

O job persistido no backend continua em:

```text
C:\TCC\perfume-3d-backend\storage\models\<jobId>.glb
```

As fotos reais de entrada usadas na galeria ficam em:

```text
C:\TCC\perfume-3d-backend\storage\models\demo-ia\phase5-preprocessed\
C:\TCC\perfume-3d-backend\storage\models\demo-ia\empire-blue-original\
C:\TCC\perfume-3d-backend\storage\models\demo-ia\empire-blue-preprocessed\
C:\TCC\perfume-3d-backend\storage\uploads\<jobId>\        # para o exemplo persistido
```

As imagens da Fase 5 vêm de:

```text
C:\TCC\evidencias\smoke-hunyuan-novo-perfume-2026-05-15\preprocessed
```

As imagens do Empire azul vêm de:

```text
C:\imagens_Novas
C:\TCC\evidencias\smoke-hunyuan\preprocessed
```

Observação importante: cada card da galeria deve permanecer ligado ao conjunto
de fotos visualmente correspondente ao seu GLB. Os dois cards da Fase 5 usam o
perfume preto/dourado; o card da Fase 3 usa o Empire azul.

| Item | Origem | Fotos | Modelo final | Tamanho aproximado |
|---|---|---:|---|---:|
| Smoke Fase 5 — resultado final com topo | `scripts/smoke_phase5.py` | 5 preprocessadas do perfume preto/dourado | `storage/models/demo-ia/phase5_with_top.glb` | 79.6 MB |
| Smoke Fase 5 — com label frontal | `scripts/smoke_phase5.py` | 5 preprocessadas do perfume preto/dourado | `storage/models/demo-ia/phase5_with_label.glb` | 65.8 MB |
| Smoke Fase 3 — 6 imagens refinado | `scripts/smoke_phase3.py` | 6 originais do Empire azul (`C:\imagens_Novas`) | `storage/models/demo-ia/phase3_perfume_refined_6_images.glb` | 28.9 MB |
| `f34cf6e0-4053-49ef-a3bf-4f3d2dfc2a32` | Hunyuan3D-2mv | 4 | `storage/models/f34cf6e0-4053-49ef-a3bf-4f3d2dfc2a32.glb` | 26.5 MB |

Observação: os jobs `f5227743-78da-48a4-9af8-83f2e7435b54` e
`54dbee08-f1e3-408e-b64e-828ca12e5b7d` existem e continuam acessíveis em
`storage/models/`, mas foram removidos da galeria principal por não serem os
melhores exemplos visuais para apresentação.

## Diferença em relação a `TCC_eval_data`

O diretório:

```text
C:\TCC\TCC_eval_data\outputs\ia
```

contém modelos de avaliação/benchmark usados para comparar branches como
`IA`, `Blander` e `Meshroom` em `results.csv`.

Esses arquivos são úteis para análise experimental, mas **não são a fonte
principal da demonstração do fluxo real do sistema**. Para demonstrar a solução
do projeto, usamos os jobs reais salvos pelo backend em `storage/models/` e suas
respectivas fotos em `storage/uploads/`.

## Roteiro sugerido para apresentação

1. Abrir a galeria.
2. Selecionar um job Hunyuan na lateral.
3. Mostrar as fotos reais de entrada na seção inferior.
4. Girar o `.glb` no viewer e explicar:
   - o app envia imagens para o backend;
   - o backend cria um job assíncrono;
   - o pipeline integrado usa Hunyuan3D-2mv;
   - os smokes Fase 3/Fase 5 demonstram os estágios de refino, label e topo;
   - o resultado final é um `.glb` visualizável pelo `<model-viewer>`;
   - no fluxo do app, esse arquivo é entregue ao Flutter como `modelUrl`.

## Observações técnicas

- A página usa `<model-viewer>` via CDN. Para a galeria HTML, é recomendável
  haver internet durante a apresentação.
- O app Flutter continua sendo o fluxo principal. A galeria é apenas um apoio
  para abrir rapidamente modelos já processados, sem esperar uma nova inferência
  durante a demonstração.
- Os modelos em `storage/` são artefatos locais de runtime e normalmente não
  devem ser versionados no Git.
- A comparação com `Meshroom` permanece relevante no texto acadêmico: os
  resultados de avaliação mostram que a fotogrametria tradicional falhou em
  vários frascos reflexivos/translúcidos, enquanto o pipeline de IA produziu
  modelos utilizáveis para visualização.
