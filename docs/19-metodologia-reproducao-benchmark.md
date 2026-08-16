# 19 — Metodologia e reprodução do benchmark 3D

**Data da auditoria:** 16/08/2026  
**Status:** metodologia histórica reconstruída; reexecução completa não realizada neste turno  
**Decisão:** o benchmark pode ser refeito, mas precisa de reparos de reprodutibilidade e de uma nova pasta de execução antes de voltar a gerar modelos

## Objetivo

Explicar, com base no código e nos artefatos preservados:

1. como o benchmark anterior foi planejado e executado;
2. quais dados, métodos, métricas e testes estatísticos foram usados;
3. o que os resultados realmente permitem concluir;
4. quais problemas foram encontrados posteriormente;
5. se é possível executar o experimento novamente e quais correções são necessárias.

As principais fontes são:

- [`eval/benchmark.py`](../eval/benchmark.py), orquestrador executável;
- [`run_benchmark.py`](../run_benchmark.py), adaptador da IA;
- [`eval/blender_scripts/render_cardinal_views.py`](../eval/blender_scripts/render_cardinal_views.py), gerador das imagens;
- [`eval/metrics/geometric.py`](../eval/metrics/geometric.py), métricas;
- [`eval/analysis.py`](../eval/analysis.py), agregação e teste estatístico;
- [`eval/BENCHMARK_JOURNEY.md`](../eval/BENCHMARK_JOURNEY.md), registro histórico das decisões e falhas;
- `C:\TCC\TCC_eval_data`, dataset, imagens, saídas e CSV preservados.

Quando a documentação histórica e o código divergem, este documento identifica a diferença. O código executável mostra o comportamento implementado; o diário explica a intenção e a configuração usada em maio/junho de 2026.

## Resposta direta

O benchmark anterior adotou um protocolo de **render-and-reconstruct** (renderizar um modelo 3D conhecido em imagens 2D e tentar reconstruí-lo novamente):

```text
GLB de referência
  -> Blender gera imagens sintéticas
  -> cada método reconstrói um novo GLB a partir das imagens
  -> superfícies do GLB reconstruído e do original são amostradas
  -> métricas geométricas são calculadas
  -> resultados são salvos em CSV e analisados estatisticamente
```

Isso torna possível conhecer o **ground truth** (modelo de referência considerado correto), pois o GLB original é preservado. A limitação é que as “fotos” são renders do Blender, não fotografias reais de celular acompanhadas por um scan 3D.

É possível refazer um benchmark equivalente e até metodologicamente melhor. Não é possível prometer uma reprodução byte a byte do resultado histórico, porque não foram registrados a semente de geração do Hunyuan, o digest do contêiner, todos os commits/configurações por execução nem as alterações locais das branches auxiliares.

## Analogia didática

O processo é semelhante a colocar uma escultura conhecida em uma cabine fotográfica, tirar fotografias padronizadas e entregar apenas as fotografias a três escultores. Depois, mede-se quanto a nova escultura de cada um se afasta da original.

**Correspondência técnica:** a escultura original é o GLB de referência; a cabine é o renderizador Blender; os escultores são Hunyuan, template Blender e Meshroom; a régua é o conjunto de métricas geométricas.

**Limitação da analogia:** os métodos não receberam exatamente a mesma quantidade de imagens. Hunyuan e template receberam quatro; o Meshroom recebeu 28, porque depende de grande sobreposição. Portanto, o benchmark compara configurações operacionais dos sistemas, não eficiência algorítmica sob entrada idêntica.

## 1. Dataset usado como referência

O diretório `C:\TCC\TCC_eval_data\held_out` contém 13 arquivos GLB públicos, acompanhados por `manifest.json` com fonte, autor e licença.

Distribuição confirmada nesta auditoria:

| Categoria | Quantidade |
|---|---:|
| Cilíndrico | 7 |
| Ornamental | 5 |
| Retangular | 1 |
| Redondo | 0 |
| Quadrado | 0 |
| **Total** | **13** |

### Localização exata dos 13 modelos

Raiz comum:

```text
C:\TCC\TCC_eval_data\held_out
```

O `manifest.json` que relaciona identificador, arquivo, categoria, autoria e licença também está nessa pasta.

| # | Identificador no benchmark | Categoria | Arquivo dentro de `held_out` |
|---:|---|---|---|
| 1 | `lancome_la_nuit_tresor` | ornamental | `perfume_bottle.glb` |
| 2 | `michaela_pink_crystal_cylindrical` | cylindrical | `perfume_bottle (1).glb` |
| 3 | `nima_frame_perfume` | cylindrical | `perfume_bottle (2).glb` |
| 4 | `shadow_assets_inherited` | cylindrical | `perfume_inherited_from_my_mother.glb` |
| 5 | `kolumbus_voy_perfume` | cylindrical | `voy_perfume.glb` |
| 6 | `vidhanchalke_perfume` | cylindrical | `perfume.glb` |
| 7 | `thepolygonic_diamond` | cylindrical | `fancy_perfume_bottle (1).glb` |
| 8 | `productviz_vanilla_leather` | cylindrical | `vanilla_leather_perfume_bottle__3d_model.glb` |
| 9 | `solblyat_golden_fancy` | ornamental | `fancy_perfume_bottle.glb` |
| 10 | `vmm_porcelain_bottle` | ornamental | `porcelain_bottle.glb` |
| 11 | `jonas_hilschmann_perfume3` | ornamental | `perfume3.glb` |
| 12 | `joankeops_ampolleta` | ornamental | `ampolleta.glb` |
| 13 | `canary_games_dior_addict` | rectangular | `10_dior_addict_3december2019.glb` |

Todos os 13 caminhos foram encontrados e aprovados novamente por `python -m eval.held_out_dataset --validate` em 16/08/2026.

Os modelos usam licenças CC0 ou CC-BY. Eles não são os mesmos arquivos usados como templates pela branch Blander.

### Significado correto de “held-out”

**Held-out** (conjunto separado do desenvolvimento do modelo e reservado para avaliação) é parcialmente adequado aqui:

- os 13 GLBs não eram templates de entrada da branch Blander;
- eles não foram usados para treinar localmente o Hunyuan;
- porém foram consultados durante a depuração do renderizador e do protocolo.

Consequentemente, eles servem como conjunto piloto e comparativo, mas não devem ser apresentados como teste confirmatório completamente intocado. Um resultado final mais forte exige outro conjunto que só seja aberto depois de congelar código e critérios.

## 2. Como as imagens sintéticas foram geradas

Para cada GLB, o Blender 5.1 executou em modo **headless** (sem interface gráfica) o script [`render_cardinal_views.py`](../eval/blender_scripts/render_cardinal_views.py).

### Padronização geométrica e da câmera

O script:

1. importa o GLB e remove a hierarquia criada pela conversão Y-up para Z-up;
2. centraliza o conjunto de meshes na origem;
3. escala o maior eixo para `1,6` unidade;
4. aplica a rotação `rotate_z_deg` declarada no manifest;
5. usa câmera de 50 mm a distância `4,5`, com pequena elevação de `0,1`;
6. renderiza PNG quadrado de `512 × 512` pixels;
7. usa EEVEE com amostragem reduzida para acelerar o processo.

As quatro posições cardeais implementadas são:

| Nome | Posição da câmera |
|---|---|
| `front` | eixo `-Y`, olhando para a origem |
| `right` | eixo `+X` |
| `back` | eixo `+Y` |
| `left` | eixo `-X` |

Além delas, foram geradas 24 posições orbitais. Combinadas com as quatro cardeais, formam 28 azimutes ao redor do objeto.

### Dois modos de entrada

Cada modelo foi renderizado duas vezes:

| Modo | Tratamento | Pergunta experimental |
|---|---|---|
| `matte` | substitui todos os materiais por cinza opaco, fundo branco e iluminação de três pontos | quão bem a forma é reconstruída quando aparência e transparência são controladas? |
| `realistic` | preserva vidro, metal e texturas; usa HDRI e contraluz | como o método reage a reflexos e transparência em uma simulação mais próxima de produto? |

O modo `realistic` continua sendo sintético. Ele aproxima propriedades ópticas, mas não inclui ruído de sensor, foco, exposição automática, movimento, fundo real ou variação de celular.

As 728 imagens preservadas estão completas:

```text
13 modelos × 2 modos × 28 imagens = 728 PNGs
```

## 3. Métodos comparados

Três branches foram expostas por um contrato uniforme de linha de comando:

```text
python run_benchmark.py --views-dir <pasta> --output-glb <arquivo.glb>
```

O backend FastAPI não precisava ser iniciado. Cada adaptador chamava seu pipeline diretamente; no caso da IA, o cliente ainda precisava que o contêiner Hunyuan estivesse disponível por HTTP.

### 3.1 IA — Hunyuan3D-2mv

- recebeu `front`, `left`, `back` e `right`;
- recebeu também os rótulos dessas vistas, evitando classificação posicional ambígua;
- executou pré-processamento, remoção de fundo e Hunyuan3D-2mv;
- gerou um GLB novo;
- no protocolo histórico, cache e fallback para template deveriam estar desabilitados;
- stages de acabamento Blender e rótulo foram desabilitados para concentrar tempo e análise em geometria.

Configuração histórica documentada:

- octree: `384`;
- 75 passos de inferência;
- textura: `1024`;
- `birefnet-general` para remover fundo;
- cache desligado;
- fallback para template desligado na execução final;
- refinador, cleaner e stages de label desligados.

### 3.2 Blander — seleção de template

“Blander” é o nome histórico da branch de baseline Blender.

- recebeu as mesmas quatro vistas cardeais;
- o CLIP classificou as imagens entre seis descrições de formatos;
- o vencedor selecionou um dos seis GLBs normalizados;
- `PROCESSOR_TYPE=template` fez o Blender exportar o template selecionado;
- o ajuste de silhueta de `template_fitting` não foi usado na configuração final.

Assim, esse baseline mede a qualidade de **selecionar uma forma pronta**, não uma reconstrução geométrica livre. É esperado que diferentes perfumes produzam arquivos idênticos quando o CLIP escolhe o mesmo template.

### 3.3 Meshroom — fotogrametria AliceVision

- recebeu as quatro cardeais e as 24 orbitais;
- executou `meshroom_batch.exe` com o pipeline `photogrammetryObject`;
- tentou estimar câmeras por SfM;
- tentou construir e texturizar um OBJ;
- o adaptador converteria o OBJ para GLB com `trimesh`.

**SfM — Structure from Motion** (estrutura a partir do movimento, técnica que encontra pontos visuais correspondentes entre fotos e usa essas correspondências para estimar câmeras e geometria) falhou nos casos registrados. Vidro, reflexos e superfícies uniformes produzem correspondências instáveis ou insuficientes.

## 4. Orquestração ponta a ponta

Para cada combinação de modelo e modo, [`benchmark_model`](../eval/benchmark.py) executava:

1. localizar `synthetic_views/<modelo>/<modo>`;
2. reutilizar as imagens se os quatro arquivos cardeais e pelo menos 24 orbitais já existissem;
3. chamar sequencialmente cada `run_benchmark.py` em seu ambiente virtual;
4. receber pela última linha do `stdout` um JSON com `status`, caminho e duração;
5. em sucesso, calcular as métricas contra o GLB original;
6. em falha, registrar o erro sem interromper os demais métodos;
7. fazer upsert no CSV após cada modelo/modo.

A chave histórica do CSV é:

```text
(model_id, branch, render_mode)
```

O CSV contém ainda categoria, status, duração, cinco métricas e erro. Não contém `run_id`, repetição, commit, checkpoint, digest de contêiner, seed do gerador ou hash das entradas/saídas.

## 5. Métricas geométricas

O módulo [`geometric.py`](../eval/metrics/geometric.py) carrega cada GLB com `trimesh`, concatena a cena como mesh e faz o seguinte:

1. copia cada malha;
2. centraliza sua *bounding box* na origem;
3. normaliza individualmente a diagonal da caixa delimitadora para `1`;
4. amostra 30.000 pontos uniformemente por área da superfície, com seed `0`;
5. usa árvores `cKDTree` para localizar vizinhos mais próximos;
6. calcula cinco métricas.

| Métrica | Interpretação | Melhor valor |
|---|---|---|
| Chamfer L1 | soma das distâncias médias entre predição→referência e referência→predição | menor |
| Chamfer L2 | mesma ideia, elevando distâncias ao quadrado e aumentando a penalização de erros grandes | menor |
| Hausdorff | maior vizinho mais próximo observado; representa o pior erro amostrado | menor |
| F-Score@1% | média harmônica entre precisão e cobertura dentro de 1% da diagonal | maior |
| F-Score@5% | versão mais tolerante, com limiar de 5% | maior |

### O que a normalização remove

Como cada GLB é centralizado e escalado separadamente, as métricas comparam **forma relativa**, não:

- tamanho físico em milímetros;
- posição global;
- escala absoluta do frasco.

A rotação não é corrigida. O ICP, citado como trabalho futuro na documentação antiga, não foi implementado. Uma saída geometricamente correta, mas girada, pode ser penalizada.

## 6. Análise estatística

[`eval/analysis.py`](../eval/analysis.py) fez três operações:

1. taxa de sucesso por método;
2. média e desvio-padrão das métricas entre linhas com `status=ok`;
3. teste de Wilcoxon pareado entre IA e Blander para Chamfer L1 e F-Score@1%, separando `matte` de `realistic`.

**Wilcoxon pareado** (teste estatístico não paramétrico que verifica se as diferenças entre dois métodos, medidas nos mesmos frascos, tendem sistematicamente para um lado) usou somente modelos em que ambos os métodos tiveram sucesso.

Um `p < 0,05` indica que uma diferença tão consistente seria pouco compatível com a hipótese de ausência de diferença. Não significa “95% de chance de a IA ser melhor”.

O script não calcula:

- intervalo de confiança;
- tamanho de efeito;
- correção para quatro comparações;
- teste pareado da taxa de falha;
- múltiplas gerações do mesmo frasco.

## 7. Resultados históricos preservados

O resumo original informa:

| Modo | Método | Sucessos | Chamfer L1 médio | F-Score@1% médio |
|---|---|---:|---:|---:|
| matte | IA | 13/13 | 0,0370 | 0,5637 |
| matte | Blander | 13/13 | 0,1053 | 0,1364 |
| realistic | IA | 11/13 | 0,0350 | 0,5303 |
| realistic | Blander | 11/13 | 0,0971 | 0,1492 |

O CSV preservado possui 76 linhas, não as 78 esperadas por `13 × 3 × 2`. Faltam as duas combinações Meshroom do modelo `jonas_hilschmann_perfume3`. O resultado observado do Meshroom é 0 sucessos em 24 tentativas registradas.

A soma histórica das durações registradas foi aproximadamente:

| Método | Execuções registradas | Soma | Mediana por execução |
|---|---:|---:|---:|
| IA | 26 | 5,93 h | 802 s |
| Blander | 26 | 0,22 h | 12,9 s |
| Meshroom | 24 | 12,27 h | 94,4 s |

Os tempos do Meshroom incluem timeouts e os registros sofreram influência de aquecimento do notebook; não devem ser tratados como estimativa limpa de desempenho.

## 8. Problemas descobertos depois da execução

### 8.1 Artefato IA contaminado

Os arquivos:

```text
TCC_eval_data/outputs/ia/lancome_la_nuit_tresor__realistic.glb
TCC_eval_data/outputs/blander/kolumbus_voy_perfume__realistic.glb
```

são byte a byte idênticos e têm SHA-256:

```text
A60760322EA0C4028F65C14FEB5C792FD4FA6476FA4B1623ACEF4C8DB961A3AF
```

O primeiro foi registrado como IA/Lancome, mas é incompatível com uma geração Hunyuan nativa daquele caso. A evidência preservada não permite distinguir definitivamente cache de fallback histórico. A linha 28 do CSV deve ser invalidada.

Ao retirar essa linha, a comparação `realistic` ainda permanece significativa:

- Chamfer L1: 10 pares, `p=0,001953`;
- F-Score@1%: 10 pares, `p=0,003906`.

Isso preserva o sinal geral do resultado histórico, mas não torna a linha contaminada válida.

### 8.2 Reutilização fraca de renders

O orquestrador considera o render reutilizável apenas pela existência dos PNGs. Ele não confere:

- hash do GLB original;
- versão do Blender;
- parâmetros de câmera e iluminação;
- hash do script;
- resolução efetiva.

### 8.3 CSV mistura versões

O upsert substitui a linha anterior com a mesma chave e `--skip-existing` pula qualquer linha `ok`. Não existe identidade da execução. Assim, rodadas com commits ou configurações diferentes podem acabar no mesmo CSV.

### 8.4 Configuração não congelada

O orquestrador atual força somente `CACHE_ENABLED=false`. As demais variáveis vêm do `.env` de cada worktree. O `.env` atual da IA habilita refinador, rótulo, costas, topo e otimização, enquanto o protocolo histórico desligava esses estágios.

### 8.5 Geração sem repetição controlada

A amostragem das métricas usa seed `0`, mas o runner não expõe uma seed do Hunyuan. Cada frasco foi gerado uma vez por modo. Logo, o benchmark não mede a variabilidade probabilística da reconstrução.

### 8.6 Viés de casos completos

As médias consideram somente sucessos de cada método, e o Wilcoxon somente pares em que IA e Blander funcionaram. Um método que falha justamente nos casos difíceis pode parecer melhor entre os casos restantes.

### 8.7 Limitações geométricas não medidas

Não foram medidos:

- escala física;
- consistência de normais;
- buracos e *watertightness*;
- componentes desconectados;
- faces não manifold;
- auto-interseções;
- silhueta em vistas retidas;
- erros separados em corpo, tampa, gargalo e borrifador.

## 9. É possível executar novamente hoje?

### Estado confirmado em 16/08/2026

| Componente | Estado |
|---|---|
| 13 GLBs e manifest | presentes e validados |
| 728 renders sintéticos | presentes e completos |
| CSV e análise histórica | presentes |
| Blender 5.1.1 | instalado e responde |
| Meshroom 2025.1.0 | instalado e responde |
| três ambientes virtuais | presentes; os três `--help` funcionam |
| worktrees Blander/Meshroom | diretórios presentes, mas vínculo Git aponta para o antigo `C:\TCC\back` |
| caminho da IA no orquestrador | desatualizado: `C:\TCC\back`; o repositório atual é `C:\TCC\perfume-3d-backend` |
| adaptador Blander | `run_benchmark.py` existe, mas está não rastreado no Git da branch |
| adaptador Meshroom | runner, processor e configuração existem como alterações locais não commitadas |
| serviço Hunyuan | Docker Engine não estava em execução nesta auditoria |

### Checklist consolidado de correções

As correções abaixo estão separadas por prioridade. “P0” bloqueia ou coloca em risco a própria execução; “P1” é necessária para chamar o resultado de reprodutível; “P2” fortalece a validade acadêmica, mas não impede um smoke test inicial.

#### P0 — necessárias antes de gerar novos resultados

1. **Preservar o histórico:** tornar `C:\TCC\TCC_eval_data` somente leitura para a nova execução e registrar seu hash antes de qualquer ação.
2. **Salvar as alterações locais das worktrees:** o runner Blander está não rastreado; runner, processor e configurações Meshroom também não estão integralmente versionados. Eles precisam ser preservados e revisados antes de reparar Git.
3. **Reparar os vínculos das worktrees:** `C:\TCC_blander\.git` e `C:\TCC_meshroom\.git` ainda apontam para o antigo `C:\TCC\back`.
4. **Remover o caminho fixo da IA:** substituir `C:\TCC\back` em [`eval/benchmark.py`](../eval/benchmark.py), linhas 49–52, por argumento de CLI ou configuração explícita apontando para `C:\TCC\perfume-3d-backend`.
5. **Fixar e versionar os três executores:** escolher um commit por método, exigir árvore limpa e guardar os adaptadores de benchmark no Git.
6. **Restabelecer o Hunyuan:** iniciar Docker, verificar `/health`, checkpoint realmente carregado, GPU visível e modo multivista antes do smoke test.
7. **Congelar dependências:** registrar versões dos três ambientes Python, Blender, Meshroom, CUDA, driver e bibliotecas; `--help` não comprova que os modelos/pesos necessários estão disponíveis.
8. **Criar uma raiz de execução nova:** separar dataset original de `synthetic_views`, `outputs`, logs e CSV do novo `run_id`.
9. **Impedir reaproveitamento cego de renders:** gerar imagens novas ou validar cada conjunto por hash do GLB, script, Blender, câmera, luz, resolução e modo. Hoje basta o PNG existir para ser reutilizado.
10. **Solicitar os dois modos explicitamente:** o default executável atual é somente `matte`; usar `--render-mode matte realistic` quando a metodologia exigir ambos.
11. **Desligar otimizações de produção:** forçar `CACHE_ENABLED=false` e impedir qualquer fallback que substitua silenciosamente o método avaliado.
12. **Congelar o escopo do pipeline:** decidir antes se será avaliado `raw.glb` de forma ou GLB final. Para geometria pura, desabilitar refinador, rótulo, costas, topo, Draco, preview e paint; não deixar isso depender do `.env` cotidiano.
13. **Fazer smoke test por método:** um frasco pequeno em cada runner antes da campanha completa, validando GLB, origem, logs e ausência de hashes indevidos.

#### P1 — necessárias para um benchmark reprodutível

14. **Adicionar identidade da execução:** registrar `run_id`, repetição, tentativa e timestamps em cada linha.
15. **Substituir o upsert destrutivo por log append-only:** preservar todas as tentativas; não sobrescrever por `(model_id, branch, render_mode)`.
16. **Não usar `--skip-existing` no ensaio confirmatório:** ele não verifica commit, configuração, seed ou checkpoint e pode misturar versões.
17. **Registrar proveniência efetiva:** método realmente executado, `origem`, checkpoint, commit, estado sujo, digest da imagem Docker e configuração segura completa.
18. **Registrar hashes:** SHA-256 do manifest, de cada GLB de referência, renders, scripts e GLBs produzidos.
19. **Controlar aleatoriedade:** expor seed quando possível e executar ao menos três repetições do Hunyuan; quando seed não existir, registrar explicitamente essa limitação.
20. **Registrar degradações reais:** resolução/octree efetivamente usada, fallback interno, textura ligada/desligada, número de imagens aceitas e modo multivista/single-view.
21. **Medir operação:** pico de RAM/VRAM, duração, temperatura e motivo de falha; hoje `peak_vram_mb` retorna `null` nos runners.
22. **Preservar logs e intermediários em falhas:** especialmente no Meshroom, cujo `TemporaryDirectory` é removido ao sair e apaga evidências úteis do erro.
23. **Controlar calor e fragmentação:** alternar métodos/modos, executar em blocos, reiniciar Hunyuan em pontos predefinidos e não reinterpretar timeouts térmicos como falha do modelo.
24. **Validar cardinalidade antes da análise:** uma repetição completa deve produzir 78 registros planejados, incluindo linhas de erro; o CSV antigo tem apenas 76.
25. **Bloquear colisões indevidas:** hash de uma saída IA idêntico a um template de outro perfume deve invalidar automaticamente a tentativa.
26. **Invalidar formalmente a linha contaminada:** não reutilizar IA/Lancome realistic do CSV histórico e gerar novamente esse caso em protocolo limpo.

#### P2 — necessárias para uma conclusão acadêmica mais forte

27. **Criar conjunto confirmatório novo:** os 13 modelos atuais foram usados na depuração do protocolo; devem funcionar como piloto.
28. **Balancear morfologias:** acrescentar modelos retangulares, redondos e quadrados, hoje ausentes ou sub-representados.
29. **Definir a pergunta sobre quantidade de vistas:** documentar se o objetivo é comparar cada sistema no seu melhor regime, como antes, ou comparar todos com a mesma informação. Quatro contra 28 vistas responde à primeira pergunta, não à segunda.
30. **Pré-registrar alinhamento e escala:** decidir entre orientação canônica e ICP, e se a escala física será preservada. A normalização atual elimina dimensões absolutas.
31. **Adicionar métricas geométricas/topológicas:** Hausdorff percentil 95, normais, buracos, *watertightness*, componentes, faces não manifold, auto-interseções e proporções.
32. **Adicionar validação por vistas retidas:** comparar silhueta e profundidade em ângulos que não foram usados para reconstruir.
33. **Separar forma de aparência:** geometria deve ser medida antes de rótulo/material; textura, vidro e legibilidade precisam de métricas visuais próprias.
34. **Melhorar a estatística:** intervalos de confiança, tamanho de efeito, correção de Holm, teste da taxa de falha e agregação das repetições por frasco.
35. **Tratar falhas e ausências no desenho estatístico:** evitar que avaliar somente pares bem-sucedidos esconda os casos mais difíceis.
36. **Definir critérios de avanço antes dos resultados:** limiares para Chamfer, F-Score, sucesso, topologia, tempo e memória devem ser pré-registrados.
37. **Adicionar validação externa com fotos reais:** para generalizar ao aplicativo, usar fotografias de celular acompanhadas por scan 3D ou medições físicas.
38. **Atualizar documentação divergente:** corrigir caminhos antigos, default de `render_mode`, contagem 76/78 e qualquer alegação de conjunto totalmente intocado.

O smoke test pode começar após os itens 1–13. Uma nova conclusão quantitativa defensável exige também os itens 14–26. Os itens 27–38 são necessários para transformar o piloto atual em uma avaliação acadêmica mais forte e generalizável.

Conclusão operacional:

- **reanalisar o CSV antigo:** possível agora;
- **rodar o comando histórico sem alterações:** não;
- **refazer um benchmark novo após reparos:** sim;
- **reproduzir exatamente os mesmos bytes:** não é garantido.

## 10. Estratégia recomendada de reprodução

Há duas metas diferentes.

### Opção A — replicação histórica aproximada

Objetivo: repetir o protocolo de 2026 com configuração equivalente.

Necessita:

1. preservar uma cópia dos adaptadores locais Blander/Meshroom;
2. reparar os vínculos das worktrees depois da renomeação do repositório;
3. registrar qual commit da IA será usado;
4. reproduzir explicitamente os `.env` históricos;
5. usar uma pasta nova e nunca sobrescrever `TCC_eval_data/results.csv`;
6. aceitar que Hunyuan pode gerar malha diferente por ausência de seed preservada.

Essa opção permite verificar se a tendência IA > template reaparece, mas não recupera exatamente a execução original.

### Opção B — benchmark contemporâneo e reprodutível — recomendada

Objetivo: avaliar o pipeline atual e futuros candidatos, incluindo LingBot, sob um protocolo melhor.

Antes de gerar modelos, alterar o orquestrador para:

- aceitar caminhos de worktree pela CLI em vez de constantes;
- separar `dataset_root` de `run_output_root`;
- exigir um `run_id` novo;
- registrar commit, estado sujo, configuração, checkpoint e digest Docker;
- registrar SHA-256 de entradas e saídas;
- nunca reutilizar render sem conferir seu manifest;
- armazenar `origem` e modo efetivamente executado;
- registrar fallback de octree e falhas CUDA;
- suportar três repetições por frasco;
- alternar a ordem dos métodos e modos;
- preservar toda tentativa, sem upsert destrutivo;
- incluir seed quando o método oferecer esse controle.

## 11. Configuração mínima para um novo benchmark geométrico

### IA atual

Para medir principalmente a forma e reduzir pós-processamentos diferentes:

```dotenv
CACHE_ENABLED=false
MESH_REFINER_TYPE=disabled
TRANSPARENCY_CLASSIFIER_TYPE=disabled
LABEL_EXTRACTOR_TYPE=disabled
LABEL_UPSCALER_TYPE=disabled
LABEL_PROJECTOR_TYPE=disabled
TOP_PROJECTOR_TYPE=disabled
BACK_PROJECTOR_TYPE=disabled
GLB_OPTIMIZER_TYPE=disabled
PREVIEW_RENDERER_TYPE=disabled
```

No contêiner Hunyuan, `HUNYUAN_ENABLE_TEXTURE=0` evita executar o paint quando a pergunta primária é somente geometria. Se a textura fizer parte da pergunta, ela deve virar um braço separado e ser avaliada por métricas visuais próprias.

### Baselines históricos

```dotenv
# Blander
PROCESSOR_TYPE=template
CLASSIFIER_TYPE=clip

# Meshroom
PROCESSOR_TYPE=meshroom
MESHROOM_PIPELINE=photogrammetryObject
MESHROOM_TIMEOUT_SECONDS=1800
```

Configuração em arquivo deve ser versionada sem credenciais e carregada explicitamente pelo run. Não se deve depender do `.env` cotidiano do aplicativo.

## 12. Procedimento seguro proposto

### Etapa 1 — preservar o histórico

- tratar `C:\TCC\TCC_eval_data` como somente leitura;
- não usar `--skip-existing` no experimento novo;
- não gravar saídas novas em `outputs/ia`, `outputs/blander` ou `outputs/meshroom` antigos;
- arquivar o SHA-256 do CSV e dos GLBs atuais.

### Etapa 2 — reparar e versionar os executores

- corrigir o caminho da IA no orquestrador;
- reparar o vínculo Git de `C:\TCC_blander` e `C:\TCC_meshroom`;
- revisar e versionar os arquivos locais ainda não rastreados;
- executar testes separados em cada branch;
- fixar commits antes do primeiro modelo.

O comando `git worktree repair` é uma possibilidade para reparar vínculos após mover o repositório, mas deve ser usado somente depois de preservar as alterações locais não commitadas encontradas nas duas worktrees.

### Etapa 3 — criar uma execução isolada

Estrutura proposta:

```text
C:\TCC\TCC_eval_runs\<run_id>\
├── manifest-run.json
├── held_out\
├── synthetic_views\
├── outputs\
│   ├── ia\
│   ├── blander\
│   └── meshroom\
├── logs\
└── results.csv
```

O `manifest-run.json` deve registrar pelo menos:

- data e máquina;
- commits e `git status` de cada método;
- versões de Python, Blender, Meshroom, CUDA e driver;
- checkpoint do Hunyuan;
- todos os parâmetros;
- hashes do dataset e dos scripts;
- ordem das execuções;
- política de reinício e resfriamento.

### Etapa 4 — validações baratas

Comandos confirmados nesta auditoria:

```powershell
cd C:\TCC\perfume-3d-backend
.\.venv\Scripts\python.exe -B -m eval.held_out_dataset --validate
.\.venv\Scripts\python.exe -B -m pytest tests\eval -q -p no:cacheprovider
```

Resultado atual: dataset com 13 modelos válido e 52 testes de avaliação aprovados.

### Etapa 5 — smoke test

Executar primeiro um frasco pequeno em `matte`, por exemplo `joankeops_ampolleta`, uma vez em cada método. Confirmar:

- runner correto;
- cache e fallback realmente desligados;
- GLB novo criado;
- arquivo abre com `trimesh`;
- método/origem registrados;
- nenhum hash de IA coincide com um template;
- tempo e pico de VRAM registrados.

Depois de corrigir o caminho da worktree e preparar uma raiz nova contendo uma cópia imutável de `held_out`, a forma pretendida do comando é:

```powershell
$benchmarkRunRoot = "C:\TCC\TCC_eval_runs\2026-08-16-clean"
.\.venv\Scripts\python.exe -B -m eval.benchmark `
  --branches IA Blander Meshroom `
  --only joankeops_ampolleta `
  --render-mode matte `
  --eval-data-root $benchmarkRunRoot `
  --output "$benchmarkRunRoot\results.csv"
```

Esse comando é um alvo após os reparos, não funciona corretamente na checkout auditada enquanto `eval/benchmark.py` ainda apontar a IA para `C:\TCC\back`.

### Etapa 6 — execução completa em blocos

- rodar poucos frascos por bloco;
- alternar método e modo para não concentrar aquecimento em um grupo;
- registrar temperatura e VRAM;
- reiniciar o serviço Hunyuan entre blocos predefinidos;
- repetir cada geração probabilística três vezes;
- manter falhas como resultados, sem substituição silenciosa.

Na máquina usada historicamente, os três métodos acumularam mais de 18 horas registradas em uma passagem, sem contar uma campanha robusta de repetições.

Após o smoke test, uma repetição completa usaria explicitamente os dois modos — o default atual do código é somente `matte`:

```powershell
.\.venv\Scripts\python.exe -B -m eval.benchmark `
  --branches IA Blander Meshroom `
  --render-mode matte realistic `
  --eval-data-root $benchmarkRunRoot `
  --output "$benchmarkRunRoot\results.csv"
```

Não usar `--skip-existing` no ensaio confirmatório. Uma passagem histórica consumiu mais de 18 horas registradas; três repetições equivalentes ultrapassariam aproximadamente 55 horas antes de pausas e verificações. Para esse desenho, é mais realista reservar três a quatro dias de máquina.

### Etapa 7 — análise

Além das métricas antigas:

- usar Hausdorff percentil 95, menos instável que o máximo;
- medir silhueta em vistas não fornecidas;
- medir topologia e componentes;
- medir escala/proporções quando houver referência física;
- reportar intervalo de confiança e tamanho de efeito;
- comparar taxa de falha;
- agregar as repetições por frasco antes do teste pareado;
- aplicar correção de Holm quando várias hipóteses forem testadas.

O analisador atual pode ser executado assim, embora deva ser ampliado para as métricas e repetições novas:

```powershell
.\.venv\Scripts\python.exe -B -m eval.analysis `
  --csv "$benchmarkRunRoot\results.csv" `
  --out "$benchmarkRunRoot\analysis"
```

## 13. Critérios de integridade antes de aceitar o novo CSV

1. Devem existir 78 registros planejados para uma repetição de `13 × 3 × 2`, inclusive registros de erro.
2. Cada linha deve ter `run_id`, repetição e proveniência.
3. Nenhuma linha pode vir de cache ou método substituto.
4. Configuração e commit precisam ser iguais dentro de um braço experimental.
5. Outputs não podem ser reutilizados apenas pelo nome.
6. Hash IA idêntico a template precisa bloquear a análise até investigação.
7. Falhas e ausências não podem desaparecer da taxa de sucesso.
8. A análise confirmatória deve usar um conjunto novo, não consultado durante calibração.

## Validação executada nesta auditoria

- `manifest.json` e os 13 GLBs foram validados pelo loader real;
- 52 testes de `tests/eval` passaram;
- a análise foi regenerada em diretório temporário e reproduziu o resumo histórico;
- os 728 PNGs esperados foram encontrados;
- os três runners responderam a `--help` em seus ambientes virtuais;
- Blender 5.1.1 e Meshroom 2025.1.0 responderam localmente;
- o comando do orquestrador falhou antes da inferência pelo caminho antigo `C:\TCC\back`;
- o Docker Engine/Hunyuan não estava ativo;
- os vínculos Git quebrados e os arquivos não versionados das worktrees foram confirmados;
- os hashes dos outputs confirmaram a contaminação IA/Lancome.

O `results.csv` histórico permaneceu inalterado, com 12.649 bytes, última modificação em 01/06/2026 19:27:19 e SHA-256 `C49B3D07764A7CDB8A7EEE7361D9C8B2E6F36AA98F4D188729D826DED4B61628`.

### O que não foi executado

- nenhum novo render;
- nenhuma inferência Hunyuan;
- nenhuma reconstrução Meshroom;
- nenhuma geração Blander;
- nenhum reparo de worktree;
- nenhuma alteração no CSV ou nos GLBs históricos.

## Rollback e preservação

Esta auditoria adiciona somente documentação. Uma futura reexecução deve usar pasta nova. Se o experimento precisar ser abandonado, arquive ou remova apenas a pasta daquele `run_id`; o dataset e o CSV histórico permanecem intocados.

## Como explicar em uma banca

> “Utilizamos 13 modelos 3D licenciados como referência. O Blender renderizou quatro vistas cardeais e 24 vistas orbitais em condições matte e realistic. Hunyuan e o baseline de templates receberam quatro vistas; o Meshroom recebeu todas as 28, conforme o regime de cada método. Cada saída foi comparada ao modelo original por pontos amostrados da superfície, usando Chamfer, Hausdorff e F-Score, e a IA foi comparada ao baseline por Wilcoxon pareado. A auditoria posterior encontrou uma linha contaminada e limitações de proveniência. Por isso, o resultado histórico é evidência piloto, e uma nova execução deve congelar commits, configuração e hashes, registrar todas as falhas e usar um conjunto confirmatório ainda não consultado.”

## Glossário curto

- **benchmark:** experimento padronizado para comparar métodos sob regras previamente definidas.
- **ground truth:** referência considerada correta para calcular o erro.
- **render-and-reconstruct:** renderizar imagens de um 3D conhecido e reconstruí-lo a partir dessas imagens.
- **held-out:** conjunto separado para avaliação; idealmente não consultado durante desenvolvimento ou ajuste.
- **CLIP:** modelo que coloca textos e imagens em um espaço vetorial comum e permite selecionar a descrição mais compatível.
- **SfM:** estima movimento de câmera e estrutura 3D por correspondências entre imagens.
- **Chamfer:** distância média bidirecional entre duas superfícies amostradas.
- **Hausdorff:** maior erro de proximidade observado entre superfícies.
- **F-Score:** equilíbrio entre precisão e cobertura dentro de um limiar geométrico.
- **Wilcoxon pareado:** teste sobre diferenças medidas nos mesmos objetos.
- **SHA-256:** impressão digital de 256 bits usada para detectar conteúdo byte a byte idêntico.
- **run_id:** identificador único de uma execução experimental.
- **worktree:** diretório adicional do Git associado a outra branch do mesmo repositório.
