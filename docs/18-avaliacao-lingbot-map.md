# 18 — Avaliação do LingBot-Map para reconstrução de frascos

**Data da avaliação:** 16/08/2026  
**Status:** parecer arquitetural; nenhuma integração implementada  
**Decisão:** não substituir o Hunyuan3D-2mv; admitir somente um experimento isolado com critérios objetivos

## Objetivo

Avaliar se o [LingBot-Map](https://github.com/Robbyant/lingbot-map) pode melhorar o molde 3D dos frascos de perfume produzido pelo backend, considerando:

- o contrato de entrada e saída dos dois sistemas;
- a captura atual do aplicativo;
- a compatibilidade com os estágios Blender já existentes;
- a qualidade geométrica que pode ser medida pelo benchmark do TCC;
- a GPU disponível no ambiente de desenvolvimento;
- a maturidade e o custo de integração do projeto externo.

Esta avaliação não afirma qualidade com base apenas nas demonstrações do repositório. A conclusão separa evidência confirmada, inferência técnica e proposta experimental.

## Escopo e versões examinadas

- Backend local: branch `IA`, commit `69fe4e480f61c8cf2f1ac4dd25665406f89c09ec`, além do estado da árvore de trabalho observado em 16/08/2026.
- LingBot-Map: branch `main`, commit [`c95c33c992d0a6ba7d4e82aacb94ed7519ed25ee`](https://github.com/Robbyant/lingbot-map/commit/c95c33c992d0a6ba7d4e82aacb94ed7519ed25ee), de 12/08/2026.
- Artigo: [*Geometric Context Transformer for Streaming 3D Reconstruction*, arXiv v2](https://arxiv.org/html/2604.14141v2), de 16/04/2026.
- Hardware local confirmado por `nvidia-smi`: NVIDIA GeForce RTX 5050 Laptop com 8.151 MiB de VRAM.

Os pesos do LingBot-Map não foram baixados e nenhuma inferência do modelo foi executada. Portanto, a viabilidade funcional foi analisada, mas o ganho de qualidade em perfumes permanece uma hipótese a testar.

Neste documento, “molde 3D” foi interpretado como **modelo digital para visualização no aplicativo**. Se a intenção for fabricar, imprimir ou usinar um molde físico, o requisito é mais rigoroso: escala em milímetros, espessura, tolerâncias, ausência de auto-interseções e malha fechada precisariam ser validadas, e nenhum dos dois pipelines pode ser considerado pronto para isso com as evidências atuais.

## Resposta direta

O LingBot-Map **não é uma alternativa viável como substituto direto** do Hunyuan3D-2mv no pipeline atual.

Em relação apenas ao hardware, a resposta é mais favorável: **a máquina local deve conseguir executar um protótipo curto do LingBot-Map, desde que seja usada uma configuração de baixa memória e um ambiente Linux isolado**. A RTX 5050 Laptop possui aproximadamente 8 GB de VRAM, exatamente a classe de capacidade para a qual existe uma adaptação comunitária executada com 16 GB de RAM e 8 GB de VRAM. Isso demonstra possibilidade técnica, mas não torna a configuração confortável: a GPU, a RAM e o ambiente de software estão no limite mínimo, e nenhuma inferência foi executada localmente nesta avaliação.

A conclusão operacional é:

- **protótipo curto com vídeo orbital de perfume:** viável, mas ainda não comprovado por execução local;
- **parâmetros oficiais completos:** não cabem com segurança nos 8 GB de VRAM;
- **sequências longas:** possíveis somente com reduções agressivas, processamento por etapas e risco maior de falta de memória;
- **uso simultâneo com Hunyuan:** inviável na mesma GPU de 8 GB;
- **Windows nativo:** o `demo.py` com SDPA pode ser investigado, mas o caminho recomendado é Linux em WSL2 ou contêiner, porque o FlashInfer oficial suporta somente Linux e o renderizador em lote compila extensões CUDA;
- **integração como molde final:** continua inviável sem um estágio adicional de conversão da nuvem de pontos em malha.

Ele pode ser uma alternativa **experimental e paralela** se o projeto aceitar duas mudanças grandes:

1. trocar as quatro fotos cardeais por uma sequência orbital densa, ou adicionar essa sequência ao fluxo;
2. construir um novo estágio de conversão de nuvem de pontos para malha de superfície.

Mesmo nessa configuração, não há evidência publicada específica de que ele reconstrua frascos transparentes, reflexivos ou refrativos melhor que o Hunyuan. O uso mais defensável é como fonte auxiliar de pose, profundidade e pontos para um experimento controlado — não como melhoria já comprovada.

## Conceitos fundamentais

- **malha de superfície** (representação 3D composta por vértices, arestas e faces triangulares que formam a “pele” do objeto): é o formato necessário para materiais, transparência, UV, rótulo, tampa e otimização Draco.
- **nuvem de pontos** (conjunto de coordenadas 3D, possivelmente coloridas, sem faces ligando os pontos): descreve amostras da geometria, mas não constitui por si só uma superfície fechada.
- **mapa de profundidade** (imagem em que cada pixel armazena a distância estimada entre a câmera e a superfície observada): pode ser reprojetado no espaço 3D quando a câmera é conhecida.
- **pose de câmera** (posição e orientação da câmera no espaço): permite colocar os pontos inferidos de cada quadro em um sistema de coordenadas comum.
- **SLAM — Simultaneous Localization and Mapping** (localização e mapeamento simultâneos, processo que estima o movimento da câmera enquanto reconstrói o ambiente): é a classe de problema que inspira o LingBot-Map.
- **GCT — Geometric Context Transformer** (transformer de contexto geométrico que mantém quadros âncora, uma janela local e memória da trajetória): é a arquitetura usada pelo LingBot-Map para processar sequências longas.
- **GLB — GL Transmission Format Binary** (contêiner binário que pode guardar diferentes tipos de primitivas 3D): a extensão `.glb` não garante que o conteúdo seja uma malha; também pode conter pontos e câmeras.
- **UV** (coordenadas bidimensionais que associam pontos de uma imagem aos vértices de uma superfície 3D): é a base para aplicar as fotos reais sobre as faces do frasco.
- **PBR — Physically Based Rendering** (modelo de material que aproxima propriedades físicas de luz, como rugosidade, transmissão e índice de refração): é usado para representar vidro e outros materiais no GLB final.

### Analogia didática

O LingBot-Map funciona como alguém que marca milhares de pontos no ar dizendo “a superfície provavelmente passa por aqui”. O Hunyuan3D e os estágios posteriores entregam uma “pele” contínua sobre a qual é possível pintar o rótulo, separar tampa e corpo e aplicar vidro.

**Correspondência técnica:** as marcas são os pontos 3D e mapas de profundidade; a pele é a malha triangular; a pintura corresponde às coordenadas UV e aos materiais.

**Limitação da analogia:** os pontos do LingBot não vêm de um scanner físico. Eles também são previsões de uma rede neural e podem apresentar escala incorreta, ruído, regiões ausentes ou superfícies fantasmas.

## Pipeline atual confirmado

O fluxo executado por [`IntegratedPipeline.process`](../app/modules/captures/pipeline.py) é:

```text
fotos
  -> pré-processamento
  -> remoção de fundo
  -> cache opcional
  -> roteamento das vistas
  -> Hunyuan3D-2mv
  -> malha raw.glb
  -> material/refino
  -> rótulo, costas e topo
  -> Draco e preview
  -> GLB final
```

Evidências no código atual:

- o Hunyuan recebe as imagens ordenadas e produz `raw.glb` em [`pipeline.py`](../app/modules/captures/pipeline.py), linhas 157–205;
- o servidor limita a entrada a seis imagens, gera forma, limpa faces degeneradas, tenta texturização e exporta uma malha GLB em [`server.py`](../docker/hunyuan/server.py), linhas 432–518;
- o checkpoint multivista recebe as chaves `front`, `left`, `back` e `right` em [`server.py`](../docker/hunyuan/server.py), linhas 559–616;
- a projeção de fotos exige objetos do tipo `MESH`, faces, normais, vértices, materiais e camadas UV em [`project_view_texture.py`](../app/modules/captures/blender_scripts/project_view_texture.py), especialmente nas linhas 226–277, 439–550 e 572–630;
- a segmentação corpo/tampa altera `material_index` de faces reais em [`segment_bottle.py`](../app/modules/captures/blender_scripts/segment_bottle.py), linhas 184–212;
- o app coleta quatro vistas cardeais, topo opcional e extras, não um vídeo contínuo, em [`app_constants.dart`](../../perfume-3d-frontend/lib/core/constants/app_constants.dart), linhas 52–64.

Consequência: a geometria nasce principalmente no Hunyuan. Os estágios Blender atuais melhoram material, atribuição de faces, UV, textura, compactação e apresentação, mas não transformam uma nuvem de pontos em uma malha fechada.

## O que o LingBot-Map realmente entrega

O LingBot-Map foi projetado para receber imagens ordenadas ou vídeo e estimar, por quadro:

- pose e parâmetros da câmera;
- mapa de profundidade e confiança;
- mapa/nuvem de pontos 3D e confiança.

O próprio artigo define o problema como reconstrução de câmera e nuvem de pontos a partir de um fluxo de vídeo. O código confirma cabeças separadas para câmera, profundidade e pontos em [`gct_base.py`](https://github.com/Robbyant/lingbot-map/blob/c95c33c992d0a6ba7d4e82aacb94ed7519ed25ee/lingbot_map/models/gct_base.py#L25-L121).

O exportador chamado de GLB não fecha uma superfície. Ele cria um `trimesh.Scene`, adiciona um `trimesh.PointCloud` colorido e, opcionalmente, frustums de câmera em [`glb_export.py`](https://github.com/Robbyant/lingbot-map/blob/c95c33c992d0a6ba7d4e82aacb94ed7519ed25ee/lingbot_map/vis/glb_export.py#L35-L188).

Essa diferença é o principal bloqueio de integração: o arquivo tem extensão `.glb`, mas seu conteúdo não satisfaz o contrato geométrico dos scripts Blender do Perfume 3D.

## Comparação técnica

| Critério | Pipeline atual | LingBot-Map | Impacto no projeto |
|---|---|---|---|
| Problema-alvo | Reconstrução generativa de objeto | Mapeamento 3D de sequência/cena | Objetivos relacionados, mas não equivalentes |
| Entrada ideal | 4 vistas cardeais; até 6 imagens | Sequência ordenada com sobreposição | A captura atual não explora a principal vantagem do LingBot |
| Saída primária | Malha triangular texturizada | Pose, profundidade e pontos | Não é troca direta |
| GLB | Superfície com faces | Cena com nuvem de pontos/câmeras | A extensão igual mascara um contrato interno diferente |
| Completar regiões não observadas | Usa prior generativo | Depende de profundidade e contexto visual | Hunyuan tende a ser mais adequado a poucas vistas |
| Blender atual | Compatível | Incompatível sem meshing | Exige um novo estágio de reconstrução de superfície |
| Rótulo, topo e verso | Estágios já conectados | Não fornecidos | Precisariam ser reaplicados após o meshing |
| Vidro/reflexo | Há tratamento específico posterior | Sem evidência específica publicada | Risco alto para perfumes transparentes |
| Uso de fundo | Remoção antes do Hunyuan | Contexto visual ajuda a estimar pose | Remover o fundo antes do LingBot pode prejudicar o registro |
| Hardware observado | RTX 5050 Laptop, 8.151 MiB de VRAM e 15,71 GB de RAM | Configuração oficial excede 8 GB; há demonstração comunitária em 16 GB RAM + 8 GB VRAM | Protótipo de baixa memória é plausível, mas não é plug-and-play |

## Onde a proposta pode ter valor

### 1. Substituição direta — não recomendada

Copiar o GLB de pontos para o lugar de `raw.glb` faria os estágios seguintes falharem ou não produzirem o efeito esperado, pois eles percorrem polígonos, normais e UVs. Além disso, o visualizador receberia pontos, não o sólido fechado esperado como modelo do produto.

### 2. Pipeline alternativo com vídeo orbital — hipótese plausível

O artigo informa treinamento com dados de objetos, como CO3D, Objaverse e Texverse, e inclui movimentos de câmera orbitando objetos. Isso oferece fundamento para um teste com perfume opaco. Não comprova desempenho em frascos de vidro.

O fluxo experimental teria de ser:

```text
vídeo orbital RGB sem máscara
  -> LingBot-Map: pose + profundidade + confiança
  -> máscara do frasco aplicada aos pontos, não à estimativa inicial de pose
  -> fusão das vistas
  -> reconstrução de superfície
  -> limpeza e fechamento da malha
  -> segmentação/material/UV/rótulo/topo/costas
  -> GLB final
```

A reconstrução de superfície poderia usar **TSDF — Truncated Signed Distance Function** (fusão volumétrica que acumula profundidades e extrai uma isosuperfície) ou reconstrução de Poisson (método que estima uma superfície contínua a partir de pontos orientados). Nenhuma dessas etapas existe hoje no pipeline.

### 3. Referência geométrica paralela — viável para pesquisa

A nuvem pode ser alinhada à malha do Hunyuan por **ICP — Iterative Closest Point** (algoritmo que aproxima duas geometrias minimizando repetidamente a distância entre pontos correspondentes). Depois, ela pode ajudar a:

- detectar proporções muito incompatíveis com as observações;
- comparar candidatos gerados pelo Hunyuan;
- indicar regiões que merecem inspeção;
- experimentar deformação controlada da malha.

A nuvem não deve ser tratada como *ground truth*, porque também é inferida.

### 4. Seleção automática de vistas — possível, mas desproporcional

As poses estimadas poderiam selecionar quatro quadros próximos de frente, esquerda, costas e direita de um vídeo. Porém, carregar um checkpoint de aproximadamente 4,63 GB apenas para selecionar vistas tem custo alto. O app já fornece rótulos explícitos, e sensores do celular, fluxo óptico ou regras de captura provavelmente resolveriam esse problema com menor complexidade.

### 5. Checkpoint `stage1` — candidato mais coerente com quatro vistas

O README publica `lingbot-map-stage1.pt` para inferência bidirecional no VGGT. O primeiro estágio foi treinado com 2 a 24 imagens e incluiu coleções multivista não ordenadas; por isso ele é conceitualmente mais próximo das quatro fotos atuais do que o checkpoint streaming.

Ainda assim, ele produz pose/profundidade/pontos, requer uma integração adicional com VGGT e não elimina a necessidade de gerar uma malha. Deve ser tratado como outro braço experimental, não como substituição pronta.

## Hardware, dependências e maturidade

### Hardware

Hardware confirmado em 16/08/2026 por consultas somente leitura ao Windows e ao `nvidia-smi`:

| Componente | Valor observado | Interpretação |
|---|---:|---|
| GPU | NVIDIA GeForce RTX 5050 Laptop | Arquitetura recente e compatível com CUDA; ainda exige validação da pilha escolhida |
| VRAM total | 8.151 MiB | Aproximadamente 8 GB; limite mínimo para a rota comunitária de baixa memória |
| VRAM livre na inspeção | 7.264 MiB | Cerca de 0,9 GB já era consumido pelo sistema gráfico |
| Capacidade computacional CUDA | 12.0 | O FlashInfer atual lista a arquitetura 12.0 entre os alvos de compilação |
| Driver NVIDIA | 610.88 | Mais recente que o mínimo citado pelo PyTorch para a geração Blackwell/CUDA 13 |
| CPU | Intel Core 7 240H, 10 núcleos e 16 threads | Suficiente para pré-processamento e offload, embora offload reduza a velocidade |
| RAM | 15,71 GB totais; 2,35 GB livres na inspeção | Quantidade total mínima demonstrada pela comunidade, mas o estado atual não oferece memória livre suficiente |
| Disco `C:` | 95,88 GB livres | Cabe um checkpoint e um ambiente isolado; sequências e artefatos longos precisam de controle |

O checkpoint equilibrado publicado no [repositório oficial de pesos](https://huggingface.co/robbyant/lingbot-map/tree/main) ocupa aproximadamente 4,63 GB; o repositório completo de modelos ocupa 14,2 GB. O tamanho em disco não equivale diretamente ao consumo de VRAM: durante a inferência também existem ativações, mapas de profundidade, predições por quadro e o cache de atenção.

A [Tabela 7 do artigo](https://arxiv.org/html/2604.14141v2#S6.SS4) registra 13,28 GB de memória para janela 64 em 518 × 378, acima dos 8 GB locais. Portanto, os parâmetros completos usados nessa medição não cabem com segurança na RTX 5050.

Há, entretanto, uma evidência prática importante. O próprio README oficial aponta para o commit comunitário [`eeee84a`](https://github.com/ureeey/lingbot-map-rtx4060-8g/commit/eeee84a89cc97c1e39b736b46df4ee315275700b), cujo autor relata execução de uma sequência longa com **16 GB de RAM e 8 GB de VRAM**. Para conseguir isso, ele:

- reduziu a altura das imagens para 294 pixels;
- ativou `--offload_to_cpu`;
- reduziu `--num_scale_frames` de 8 para 2;
- limitou a janela do cache a 48;
- reduziu `--camera_num_iterations` de 4 para 1;
- separou inferência e criação do PLY em duas etapas;
- carregou imagens sob demanda para não manter toda a sequência na RAM.

Essa evidência torna o protótipo local **plausível**, porque a máquina tem a mesma quantidade nominal de RAM e VRAM. Ela não comprova que o código oficial, sem adaptações, executará nem que terá a mesma velocidade ou qualidade na RTX 5050. O fork diminui resolução, contexto e refinamento para caber na memória; essas escolhas podem reduzir precisão de pose e detalhe geométrico.

### Matriz de viabilidade local

| Cenário | Parecer | Motivo |
|---|---|---|
| `demo.py` curto, 50–150 quadros orbitais | **Provavelmente viável** | Sequência curta, offload e apenas 2 quadros de escala reduzem o pico |
| `demo.py` nos parâmetros completos de memória publicados | **Não viável em 8 GB** | A medição publicada chega a 13,28 GB |
| Sequência de milhares de quadros | **Viável apenas experimentalmente** | Exige lazy loading, janela/cache reduzidos, baixa resolução e pós-processamento separado |
| FlashInfer no Windows nativo | **Não suportado oficialmente** | A documentação do FlashInfer declara suporte somente a Linux |
| SDPA no Windows nativo | **Possível, mas não validado** | Evita FlashInfer; pode consumir mais memória e não cobre o renderizador CUDA completo |
| WSL2/contêiner Linux com GPU | **Rota recomendada** | Mantém a pilha Linux esperada e isola dependências do backend |
| LingBot e Hunyuan simultâneos | **Não viável** | Os dois competiriam pelos mesmos 8 GB de VRAM |
| LingBot como gerador direto do GLB final | **Não viável** | A saída é uma nuvem de pontos, não a malha esperada pelo aplicativo |

Para um primeiro teste de perfume, a sequência deve ser deliberadamente pequena: um vídeo orbital lento, inicialmente limitado a aproximadamente 50–100 quadros após amostragem. O objetivo do primeiro teste é medir pico real de VRAM/RAM e confirmar a saída, não buscar qualidade máxima.

### Impacto dos ajustes de baixa memória na qualidade

“Modo de baixa memória” não é uma única redução. Algumas opções apenas mudam onde os dados ficam armazenados; outras removem informação visual ou contexto geométrico e podem afetar a reconstrução.

| Ajuste | Economia obtida | Impacto esperado na qualidade |
|---|---|---|
| Parar Hunyuan e outras cargas da GPU | libera VRAM ocupada por outros processos | nenhum; não altera o LingBot |
| `--offload_to_cpu` | move previsões por quadro da VRAM para a RAM | nenhum impacto algorítmico esperado; aumenta transferências e pode reduzir velocidade |
| FlashInfer em vez de SDPA | usa atenção/cache mais eficiente | não é uma redução intencional de qualidade; pode mudar desempenho e pequenas diferenças numéricas |
| Limitar o vídeo mantendo uma órbita completa | reduz duração e crescimento do cache | baixo impacto se ainda houver cobertura de 360° e sobreposição suficiente |
| Aumentar `stride` ou reduzir FPS excessivamente | processa menos quadros | pode prejudicar pose e profundidade se os saltos entre vistas ficarem grandes |
| `--camera_num_iterations 4` → `1` | reduz passes da cabeça de câmera e o cache associado | pequena perda de precisão de pose prevista pelo próprio README; o tamanho real da perda em perfumes é desconhecido |
| `--num_scale_frames 8` → `2` | reduz o pico da fase inicial | pode enfraquecer a inicialização de escala/pose; não há quantificação publicada específica para perfumes |
| Reduzir resolução de 518 × 378 para aproximadamente 294 pixels de altura | reduz ativações e pontos por quadro | tende a preservar forma grossa, mas perde contornos finos, quinas pequenas, gravações e detalhes da tampa |
| Aumentar `keyframe_interval` ou reduzir muito a janela | mantém menos contexto visual no cache | pode aumentar deriva de pose em trajetórias longas; o efeito tende a ser menor em uma órbita curta |
| `downsample_factor` do visualizador/exportador | exibe/exporta menos pontos | reduz densidade do artefato visual, mas não muda a inferência original já calculada |

Assim, não é tecnicamente correto concluir que “se não cabe a configuração completa, a qualidade será muito ruim”. O resultado depende de **qual** ajuste foi necessário. Offload, execução exclusiva da GPU e redução da duração sem perder a órbita podem economizar recursos com pouca ou nenhuma perda. Resolução, quadros de escala e iterações de câmera introduzem trocas reais entre memória e precisão.

Para perfumes, a hipótese mais razoável é que um perfil leve ainda preserve silhueta e proporções gerais de um frasco opaco, enquanto detalhes pequenos e alinhamento fino tendem a degradar primeiro. Para vidro transparente ou reflexivo, a ambiguidade óptica pode dominar o erro mesmo na configuração completa; mais memória não corrige automaticamente refração e reflexos inconsistentes entre quadros.

O experimento deve reduzir uma variável por vez, usando o mesmo vídeo:

1. 518 × 378, órbita curta, `--offload_to_cpu`, 8 quadros de escala e 4 iterações de câmera; registrar se cabe.
2. Se faltar memória, manter resolução e 4 iterações, reduzindo apenas os quadros de escala para 2.
3. Se ainda faltar memória, testar 2 iterações e depois 1 iteração de câmera.
4. Reduzir resolução somente depois, pois ela afeta diretamente o detalhe espacial.
5. Comparar cada perfil por Chamfer L1, F-Score@1%, silhueta em vistas não usadas, consistência da pose e inspeção de regiões finas.

Uma execução que não cabe também é um resultado experimental válido. Ela define o limite de hardware e impede atribuir uma eventual perda de qualidade a várias reduções aplicadas simultaneamente.

Um orçamento conservador de disco para o protótipo é reservar **25–35 GB**: 4,63 GB para um checkpoint, além do ambiente PyTorch/CUDA, repositório, caches e artefatos. Esse intervalo é uma estimativa de engenharia, não um requisito publicado. Os 95,88 GB livres são suficientes para o protótipo com um único checkpoint, mas não justificam baixar todos os pesos e datasets sem necessidade.

Hunyuan e LingBot não devem permanecer carregados simultaneamente nessa GPU. Um experimento deve parar um serviço, liberar a VRAM, verificar com `nvidia-smi` e somente então iniciar o outro.

### Dependências

O LingBot recomenda Python 3.10, PyTorch 2.8/CUDA 12.8 e FlashInfer. O estado local observado ainda **não está pronto para executar o modelo**:

- o Python global é 3.14.3;
- o PyTorch global é `2.10.0+cpu`, sem CUDA, e `torch.cuda.is_available()` retorna `False`;
- Conda não está instalado ou não está no `PATH`;
- o compilador `nvcc` do CUDA Toolkit não está instalado ou não está no `PATH`;
- o WSL2 contém apenas a distribuição interna `docker-desktop`, que estava parada;
- o cliente Docker está instalado, mas o engine do Docker Desktop estava desligado.

Isso é um **bloqueio de ambiente**, não uma insuficiência definitiva do hardware. O `nvidia-smi` reconhece corretamente a RTX 5050 e o driver.

FlashInfer (biblioteca que implementa a atenção e o cache de chaves/valores de forma eficiente na GPU) declara suporte oficial somente a Linux. A RTX 5050 informa capacidade computacional 12.0, e a documentação atual do FlashInfer inclui `12.0f` entre os alvos de compilação. O PyTorch também possui suporte às GPUs Blackwell em versões com CUDA recente. A combinação é tecnicamente coerente, mas só um smoke test dentro do ambiente escolhido comprovará a compatibilidade completa.

O servidor Hunyuan atual usa uma pilha própria baseada em PyTorch 2.7 e offload `mmgp`. A opção de menor risco é um contêiner Linux separado, com checkpoint e commit fixados, em vez de misturar dependências no ambiente do backend. Uma distribuição Ubuntu própria no WSL2 também é possível; no estado atual ela ainda não existe.

Com apenas 15,71 GB de RAM total, o WSL2 ou Docker precisa dividir memória com o Windows. Para um vídeo curto isso pode funcionar após fechar aplicações pesadas e liberar RAM. Para sequências longas e execução previsível, **32 GB de RAM é a recomendação prática**, embora não seja obrigatório para o primeiro smoke test. A evidência comunitária demonstra execução em 16 GB, mas explicitamente descreve a memória como apertada.

O renderizador em lote do LingBot adiciona Kaolin, Open3D, FFmpeg e extensões CUDA. Esses componentes não são necessários para um protótipo que consuma apenas as previsões, portanto não devem entrar no primeiro experimento.

### Maturidade

Fatos observados no snapshot:

- projeto recente, ativo, versão `0.1.0` e licença Apache-2.0;
- benchmark e exemplos são voltados a cenas e trajetórias, não a malhas de perfumes;
- a interface de exportação de polígonos ainda é uma solicitação aberta no repositório;
- há inconsistência entre ajuda e código: `--offload_to_cpu` é descrito como ativo por padrão, mas o argumento está com `default=False` em [`demo.py`](https://github.com/Robbyant/lingbot-map/blob/c95c33c992d0a6ba7d4e82aacb94ed7519ed25ee/demo.py#L387-L395);
- o extra `render` citado no README não está declarado no `pyproject.toml` do snapshot.

A [licença Apache-2.0](https://github.com/Robbyant/lingbot-map/blob/c95c33c992d0a6ba7d4e82aacb94ed7519ed25ee/LICENSE.txt) permite uso e modificação, mas uma integração distribuída deve preservar os avisos e condições da licença.

## Risco específico de perfumes transparentes

Vidro, líquidos, metal polido e reflexos violam suposições comuns de reconstrução baseada em imagens:

- um raio de luz pode refratar e não corresponder à superfície aparente;
- reflexos mudam com a posição da câmera e parecem se mover sobre o frasco;
- regiões lisas têm poucos pontos visuais estáveis para registrar quadros;
- a transparência deixa fundo e conteúdo interno competirem com a superfície externa.

Não foi encontrada no artigo, código ou benchmark oficial uma avaliação específica de vidro ou frascos de perfume. A ausência dessa evidência não prova que o modelo falhará, mas impede afirmar que ele melhorará o molde.

O primeiro experimento deve separar frascos opacos/foscos de transparentes/reflexivos. Misturar os grupos esconderia a causa das falhas.

## Experimento A/B recomendado

### Pergunta experimental

“Sob um protocolo de captura explícito, o LingBot-Map ou um pipeline híbrido produz geometria de frascos mais fiel que o Hunyuan3D-2mv atual, com custo operacional aceitável?”

### Braços do experimento

| Braço | Entrada | Método | Pergunta respondida |
|---|---|---|---|
| A — baseline | 4 cardeais | pipeline atual/Hunyuan | qualidade atual |
| B — mesma informação | mesmas 4 imagens | `stage1` + meshing | efeito do método sem vantagem de mais quadros |
| C — controle de captura | 4 quadros selecionados do vídeo | pipeline atual/Hunyuan | ganho causado apenas pela captura orbital |
| D — candidato | vídeo orbital completo | LingBot + meshing | desempenho no regime para o qual o streaming faz sentido |
| E — híbrido | vídeo + 4 quadros | Hunyuan ajustado/validado pela nuvem | valor complementar da nuvem |

Os braços B, D e E exigem código novo e são propostas, não funcionalidades implementadas.

### Controle das variáveis

1. Fixar commit, checkpoint, resolução, número de quadros e parâmetros.
2. Desabilitar o cache do pipeline atual para impedir que um GLB antigo seja devolvido.
3. Usar o mesmo conjunto de frascos e o mesmo modelo de referência por par.
4. Não reutilizar o conjunto de teste para ajustar thresholds ou parâmetros de meshing.
5. Separar `opaque/matte` de `transparent/reflective` antes da análise.
6. Registrar falhas, tempo, VRAM, RAM, tamanho do arquivo e todos os artefatos intermediários.
7. Alinhar predição e referência pelo protocolo definido antes de calcular as distâncias.

### Métricas

- **Chamfer L1**: distância média bidirecional; menor é melhor.
- **F-Score@1%**: equilíbrio entre precisão e cobertura a 1% da diagonal; maior é melhor.
- **Hausdorff**: pior distância local; útil para pontos flutuantes e regiões ausentes.
- taxa de conclusão e de malhas carregáveis;
- número de componentes, presença de faces, área, volume e **watertightness** (condição de malha fechada sem bordas abertas);
- comparação de silhueta em vistas não usadas na geração;
- avaliação visual cega de tampa, rótulo, proporção e material;
- tempo, pico de VRAM/RAM e tamanho do GLB final.

O módulo [`eval/metrics/geometric.py`](../eval/metrics/geometric.py), linhas 163–243, já aceita tanto malha quanto `numpy.ndarray (N, 3)`. Isso permite avaliar a nuvem bruta, mas essa medição deve permanecer separada da avaliação da malha final: uma boa nuvem não comprova que o meshing produziu um ativo utilizável pelo app.

### Critério proposto de avanço

Antes do teste, registrar um limiar prático. Uma proposta inicial é avançar somente se o candidato:

- concluir pelo menos 90% dos frascos opacos;
- produzir malha triangular carregável e fechada no fluxo final;
- reduzir a mediana do Chamfer L1 em pelo menos 10% sem piorar o F-Score@1%;
- mostrar ganho consistente por frasco, com intervalo de confiança e teste pareado;
- não exceder o orçamento de hardware e tempo definido para a demonstração.

Os valores de 90% e 10% são critérios de engenharia propostos, não padrões universais. Devem ser definidos antes dos resultados para evitar escolher um corte que favoreça o candidato.

## Decisão e alternativas consideradas

### Decisão atual

1. Manter Hunyuan3D-2mv como gerador principal.
2. Não conectar o GLB de pontos do LingBot ao Blender atual.
3. Não alterar o contrato HTTP ou a captura Flutter antes de um *spike* isolado.
4. Se houver tempo de pesquisa, testar primeiro `stage1` com quatro vistas e, em seguida, o checkpoint streaming com um vídeo orbital curto de frasco opaco.
5. Só propor integração depois de medir a malha final no benchmark do TCC.

### Alternativas

- **Continuar apenas com Hunyuan:** menor risco e compatibilidade total; mantém as limitações generativas atuais.
- **LingBot como substituto:** descartado por incompatibilidade de saída.
- **LingBot como validador:** custo menor que um pipeline completo, mas ainda exige alinhamento e não corrige a malha sozinho.
- **LingBot + TSDF/Poisson:** tecnicamente possível e academicamente interessante, porém equivale a criar uma segunda arquitetura de reconstrução.
- **Checkpoint `stage1`:** mais coerente com poucas imagens, mas ainda requer VGGT, meshing e validação.

## Riscos e limitações residuais

- A reconstrução de superfície pode suavizar quinas, criar buracos ou fechar incorretamente o gargalo/tampa.
- Filtrar o fundo antes da pose pode retirar o contexto necessário; manter o fundo inclui pontos indesejados que precisam de máscara posterior.
- Quatro vistas com saltos de 90° oferecem pouca sobreposição para um método de registro temporal.
- O pipeline atual de UV e segmentação foi calibrado para a topologia densa do Hunyuan e pode exigir recalibração na nova malha.
- Os números publicados pelo LingBot pertencem a outros datasets e não podem ser transferidos diretamente para perfumes.
- Os resultados atuais do TCC oferecem evidência para o baseline, mas o conjunto avaliado não deve ser descrito como totalmente intocado se foi usado durante o ajuste do protocolo.
- A auditoria deste turno encontrou um artefato histórico contaminado: `TCC_eval_data/outputs/ia/lancome_la_nuit_tresor__realistic.glb` e `TCC_eval_data/outputs/blander/kolumbus_voy_perfume__realistic.glb` têm o mesmo SHA-256 (`A60760322EA0C4028F65C14FEB5C792FD4FA6476FA4B1623ACEF4C8DB961A3AF`). Isso é incompatível com uma geração Hunyuan nativa da Lancome; os artefatos preservados não permitem distinguir definitivamente cache de fallback. A linha 28 do `results.csv` deve ser invalidada e reexecutada antes de servir de baseline; nenhum resultado histórico foi alterado nesta avaliação. Ao excluí-la, a comparação histórica *realistic* ainda permanece significativa para Chamfer (`n=10`, `p=0,001953`) e F-Score@1% (`n=10`, `p=0,003906`), enquanto a taxa provisória de saídas IA válidas passa a 23/26 (88,5%).
- O script histórico [`eval/benchmark.py`](../eval/benchmark.py) aponta o backend de IA para um caminho local que não existe mais, reutiliza renders apenas pela existência do arquivo e não registra `run_id`, seed nem hash completo da configuração. Um A/B novo precisa congelar a configuração e separar os artefatos por execução para não misturar versões do pipeline.
- Há uma divergência documental local a revisar separadamente: [`17-fidelidade-do-modelo.md`](17-fidelidade-do-modelo.md) ainda descreve a textura como sempre baseada em uma única foto, enquanto o código atual de [`server.py`](../docker/hunyuan/server.py), linhas 683–715, tenta múltiplas referências e degrada para a primeira em caso de falha.

## Validação executada

### Inspeções

- metadados, árvore, README, código, benchmark, licença, commits e issues do LingBot-Map;
- artigo e repositório oficial de checkpoints;
- pipeline, servidor Hunyuan, projetores Blender, captura Flutter e benchmark local;
- hardware com `nvidia-smi` e consultas WMI/CIM do Windows;
- disponibilidade de WSL2, Docker, Python, PyTorch, Conda e CUDA Toolkit.

Comandos principais usados na verificação de hardware e ambiente:

```powershell
nvidia-smi --query-gpu=name,memory.total,memory.free,driver_version,compute_cap --format=csv,noheader,nounits
Get-CimInstance Win32_OperatingSystem
Get-CimInstance Win32_Processor
wsl --status
wsl --list --verbose
docker version
python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
where.exe conda
where.exe nvcc
```

Resultados relevantes: GPU reconhecida com 8.151 MiB de VRAM; 15,71 GB de RAM total; apenas 2,35 GB livres durante a consulta; Docker Desktop instalado, porém parado; somente a distribuição interna `docker-desktop` no WSL2; Python 3.14.3 com PyTorch `2.10.0+cpu`; Conda e `nvcc` ausentes do `PATH`. Esses testes confirmam o inventário e os bloqueios de instalação, mas não confirmam que o checkpoint caiba durante uma inferência real.

### Testes locais

Comando:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/eval tests/modules/captures/test_pipeline.py -q
```

Resultado: **83 testes aprovados**.

Esses testes oferecem evidência de que as métricas e a composição lógica local usada como base da avaliação estão operacionais. Eles **não comprovam** a qualidade visual do Hunyuan, a qualidade do LingBot, a conversão de pontos em malha nem o comportamento com fotos reais de vidro.

Também foi executada a suíte local, excluindo apenas o teste lento que chama o Hunyuan real:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; .\.venv\Scripts\python.exe -m pytest -m "not slow" -p no:cacheprovider
```

Resultado: **391 testes aprovados, 1 teste lento desmarcado e 11 avisos de depreciação do Pillow** em 39,03 s. Dois testes usam o Blender real, mas validam estrutura/material do GLB, não fidelidade geométrica ou visual. Portanto, a suíte mostra que o código local está coerente para servir de referência; ela não constitui uma comparação entre os modelos.

### O que não foi validado

- inferência local do LingBot-Map;
- consumo real de VRAM na RTX 5050;
- qualidade em vídeo orbital de perfume;
- geração de superfície a partir dos pontos;
- compatibilidade do resultado convertido com todos os estágios Blender e o viewer Flutter.

## Procedimento de rollback de um futuro protótipo

O protótipo deve ser implementado como estratégia/serviço separado e desativado por padrão. Para retornar ao comportamento atual:

1. desligar a feature flag do candidato;
2. parar/remover somente o contêiner e o volume de pesos do LingBot;
3. manter `IntegratedPipeline` apontando para `Hunyuan3DProcessor`;
4. remover artefatos experimentais sem tocar nos GLBs e registros do pipeline principal;
5. confirmar o baseline com os testes e um smoke test real.

## Pendências e próximos passos

1. Definir se o objetivo acadêmico justifica criar um segundo pipeline ou apenas comparar modelos.
2. Corrigir e versionar o protocolo do benchmark, invalidar a linha contaminada e gerar um baseline reprodutível com cache desligado, conforme [`19-metodologia-reproducao-benchmark.md`](19-metodologia-reproducao-benchmark.md).
3. Capturar um pequeno conjunto orbital, começando por 3–5 frascos opacos e mantendo transparentes em grupo separado.
4. Prototipar em contêiner isolado, sem modificar o contrato de produção.
5. Medir a nuvem bruta e a malha resultante como artefatos distintos.
6. Só então decidir se vale ampliar para um conjunto realmente não usado na calibração.

## Como explicar em uma banca

> “O LingBot-Map é um modelo de reconstrução geométrica de sequências: ele estima câmera, profundidade e nuvens de pontos. Nosso pipeline precisa de uma malha fechada com faces, UV e materiais para representar tampa, rótulo e vidro. Portanto, apesar de ambos exportarem GLB, os conteúdos não têm o mesmo contrato. Não o adotamos como substituto do Hunyuan. Propusemos um experimento em que uma captura orbital alimenta o LingBot, seus pontos são convertidos em malha e o resultado é comparado ao baseline com Chamfer, F-Score, taxa de sucesso, custo computacional e avaliação visual. Até esse experimento, qualquer ganho é hipótese, não resultado.”

## Glossário curto

- **baseline:** método atual usado como referência da comparação.
- **checkpoint:** arquivo com os pesos aprendidos por um modelo neural.
- **feed-forward:** inferência em que a rede produz a saída diretamente, sem otimização iterativa por cena.
- **frustum:** volume visível por uma câmera, representado como uma pirâmide truncada.
- **ICP:** alinhamento iterativo entre geometrias por proximidade de pontos.
- **malha watertight:** superfície fechada, sem bordas abertas, adequada para representar um sólido.
- **meshing:** processo de transformar pontos ou volumes em faces triangulares.
- **nuvem de pontos:** amostras 3D sem conectividade de superfície.
- **pose:** posição e orientação da câmera.
- **TSDF:** representação volumétrica usada para fundir mapas de profundidade e extrair superfícies.
- **VRAM:** memória dedicada da GPU.
