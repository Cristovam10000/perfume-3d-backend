# Sessão 2026-04-26 — Preparação da Fase 2: Blender, curadoria de templates e primeiro GLB normalizado

## 1. Metadados

- **Título:** Preparação do pipeline de templates 3D com Blender headless, curadoria de modelos Sketchfab e primeiro template normalizado.
- **Data aproximada:** 2026-04-26, inferida pelo commit `04c44c2`.
- **Fase do projeto:** transição entre a Fase 1 funcional com `FakeProcessor` e a Fase 2 baseada em templates paramétricos.
- **Escopo/objetivo principal:** registrar o pivot metodológico de Meshroom/AliceVision para templates, preparar o ambiente Blender, selecionar e organizar modelos 3D baixados, estabelecer regras de licença/atribuição e versionar a primeira base técnica de assets (`catalog.json`, `ATTRIBUTIONS.md`, `rectangular_basic.glb` e teste de contrato dos GLBs).
- **Posicionamento cronológico inferido:** **sessão 1 documentada** após o bootstrap sem documento. Ela ocorre depois dos commits de Fase 1 (`b724648` → `0106a1f`, 2026-04-22/23) e imediatamente antes da sessão mais ampla `historico/2026-04-26_fase2-templates-clip-cor.md`. Há sobreposição deliberada com aquele histórico: o commit `04c44c2` aparece nos dois, mas aqui ele é tratado como preparação/curadoria; no outro arquivo, como primeiro commit do bloco maior da Fase 2.
- **Commits Git associados:**

    | Hash | Data | Mensagem | Papel nesta sessão |
    |---|---|---|---|
    | `04c44c2` | 2026-04-26 | `feat(assets): add 3D template catalog and attribution documentation` | Âncora principal: `.gitignore`, catálogo, atribuições, `rectangular_basic.glb`, script de normalização inicial e testes de contrato dos templates. |
    | `408ef0f` | 2026-04-26 | `chore(docs): remove outdated context and task documentation` | Commit posterior que removeu `docs/contexto-resumido-templates.md` e `docs/task.md`; relevante como divergência documental. |
    | `f8b3c39` | 2026-04-26 | `chore(docs): remove outdated context and task documentation` | Repetição/continuação da limpeza documental; confirma que o resumo original da sessão deixou de existir no working tree atual. |

- **Sessões anteriores referenciadas:**
    - Não havia arquivo anterior em `historico/` para o bootstrap. O estado anterior é inferido pelos commits `b724648`, `6de1423`, `8e6a08e`, `19048d3`, `726fb62`, `0106a1f` e pelo `README.md` do backend.
    - O `README.md` do commit `0106a1f` ainda apresentava Meshroom/AliceVision como Fase 2 planejada; esta sessão modifica essa direção.

- **Sessões posteriores relacionadas:**
    - `historico/2026-04-26_fase2-templates-clip-cor.md`: expande o trabalho daqui para `TemplateProcessor`, normalização dos demais templates, `CLIPClassifier`, `ColorDetector` e integração no service.
    - `historico/2026-04-26_validacao-e2e-mobile-viewer-local.md`: valida no app e no viewer local a Fase 2 derivada desta preparação.
    - `historico/2026-05-09_pipeline-ia-segmentacao-e-refinamento.md`: parte do diagnóstico de que templates podem ser insuficientes visualmente e abre uma trilha IA complementar.

## 2. Contexto inicial

Antes desta sessão, o backend estava no estado imediatamente posterior ao commit `0106a1f`:

- FastAPI modular funcionando.
- `Processor` ABC e `FakeProcessor` gerando um cubo `.glb`.
- `CaptureService`, fila `asyncio.Queue`, rotas `POST /captures` e `GET /captures/{jobId}/status`.
- `main.py` com lifespan, CORS, banco e `StaticFiles`.
- `README.md` e `scripts/smoke.ps1` documentando o fluxo fake ponta a ponta.

O plano de roadmap ainda apontava para **Meshroom/AliceVision** como Fase 2:

```text
Fase 2 — Integração com Meshroom/AliceVision
```

A conversa, entretanto, já havia diagnosticado uma limitação de domínio: frascos de perfume são frequentemente transparentes, reflexivos, lisos e pouco texturizados. Em testes manuais, o Meshroom executou tecnicamente o grafo de fotogrametria, mas rejeitou muitas câmeras e gerou resultados fracos para vidro/reflexo. A necessidade da sessão foi transformar esse diagnóstico em uma direção implementável: **templates 3D pré-existentes customizados via Blender**, em vez de reconstrução geométrica literal por SfM.

Também havia modelos baixados do Sketchfab em uma pasta local externa ao repositório:

```text
C:\teste-images
```

Esses modelos ainda não estavam classificados, normalizados, documentados nem preparados para uso pelo backend.

## 3. Decisões arquiteturais e de design

### 3.1 Pivot de Meshroom para templates paramétricos

Opções consideradas na conversa:

| Opção | Decisão | Justificativa |
|---|---|---|
| Meshroom/AliceVision | Substituído como caminho principal | Falha empiricamente no domínio de vidro/reflexo/transparência, apesar de ser correto para objetos opacos e texturizados. |
| Templates paramétricos via Blender | Escolhido para Fase 2 | Mais previsível para um MVP acadêmico de vitrine 3D; permite qualidade visual controlada e execução local sem pipeline SfM pesado. |
| Modelagem procedural pura | Adiada/trabalho futuro | Gerar geometria do zero por código exigiria lidar com forma, UV, vidro, tampa e label; custo alto para qualidade visual inferior. |
| IA generativa/NeRF | Mantida como alternativa futura | Promissora para vidro/reflexo, mas adiciona dependências pesadas e incerteza operacional. |

A formulação recomendada para o TCC foi:

```text
modelagem 3D parametrica baseada em templates
```

ou:

```text
customizacao programatica de modelos base com Blender
```

### 3.2 Categoria não equivale a um único molde

Foi decidido que uma categoria de forma (`rectangular`, `cylindrical`, `square`, `round`, `ornamental`) pode conter vários templates. Para o MVP, entretanto, a estratégia inicial é escolher poucos representantes e evoluir depois.

Exemplo conceitual:

```text
rectangular_basic
rectangular_modern_reference
cylindrical_basic
square_compact
round_spherical
ornamental_modernist
```

Trade-off: começar com poucos templates reduz escopo e facilita normalização manual; manter o catálogo preparado para múltiplos templates por categoria evita engessar o modelo de domínio.

### 3.3 Licenças aceitas para modelos externos

A conversa estabeleceu uma política simples para Sketchfab:

- **CC0**: melhor opção; crédito não obrigatório, mas recomendado registrar.
- **CC-BY**: aceitável; exige crédito ao autor e link.
- **CC-BY-SA**: possível, mas complica redistribuição por exigir licença compatível.
- **CC-BY-NC**: aceitável apenas para contexto acadêmico; evitar se houver uso comercial futuro.
- **Qualquer licença com `ND`**: não usar, pois `NoDerivatives` conflita com normalização, renomeação, ajuste de material e exportação.
- **Editorial**: não usar em produto/app.
- **Standard/Free Standard**: evitadas nesta fase para reduzir ambiguidade jurídica.

Essa decisão motivou o arquivo:

```text
C:\TCC\back\assets\templates\ATTRIBUTIONS.md
```

### 3.4 Raw assets não devem entrar no Git comum

Os modelos brutos baixados somavam aproximadamente 113 MB. Foi decidido versionar metadados, créditos e templates normalizados, mas **não** versionar a pasta bruta:

```text
assets/templates/raw/
```

O `.gitignore` foi atualizado para evitar commit acidental de:

```text
contexto.md
assets/templates/raw/
storage/**/*.glb
storage/**/*.gltf
```

Trade-off: o repositório fica mais leve, mas a reconstituição exata dos arquivos brutos depende das fontes Sketchfab e dos links em `ATTRIBUTIONS.md`. Se a banca ou outro ambiente precisar reconstruir tudo offline, Git LFS ou um pacote de assets separado será necessário.

### 3.5 Blender headless como ferramenta central

Blender foi escolhido em dois papéis:

1. Ferramenta visual para abrir/importar modelos `.gltf/.glb/.fbx/.obj`.
2. Motor headless para normalizar/exportar templates e, em fases posteriores, customizá-los por script.

Executável validado na sessão:

```text
C:\Program Files\Blender Foundation\Blender 5.1\blender.exe
```

Versão:

```text
Blender 5.1.1
```

Como `blender` podia não estar no `PATH`, decidiu-se usar o caminho absoluto em configurações/scripts.

### 3.6 Primeiro template normalizado antes do processor real

Antes de implementar um `TemplateProcessor`, era necessário provar que pelo menos um asset externo podia ser convertido para o contrato interno do projeto. Por isso, o commit `04c44c2` gerou:

```text
assets/templates/normalized/rectangular_basic.glb
```

e um teste de contrato para validar GLB, nós e materiais esperados. Esse passo serviu como prova mínima de viabilidade do caminho Blender/templates.

## 4. Implementação realizada

### 4.1 Organização local dos modelos Sketchfab

Fora do Git, a pasta:

```text
C:\teste-images
```

foi organizada em:

```text
C:\teste-images\_classificados
```

Classificação registrada no resumo `docs/contexto-resumido-templates.md` do commit `04c44c2`:

```text
_classificados\
  retangulares_altos\
    10_dior_addict_3december2019
    chanel_bleu_de_chanel_edp_100ml
    perfume_bottle

  cilindricos_ou_altos_redondos\
    perfume

  quadrados_compactos\
    perfume_bottle (1)
    perfume_bottle (2)

  redondos_esfericos\
    perfume_bottle (3)

  ornamentais_porcelana_antigos\
    art_nouveau_perfume_bottle
    modernist_perfume_bottle
    perfume_bottle_with_a_landscape
    porcelain_bottle_with_an_ornamentation
    porcelain_perfume_bottle

  nao_templates\
    imagens
    novo.mg
```

`imagens` continha fotos de captura e `novo.mg` continha cache/projeto Meshroom; ambos foram classificados como não-templates.

Observação metodológica: por estar fora do repositório, essa classificação é evidência documental, não evidência Git. A âncora dura no Git é o resumo removido posteriormente (`git show 04c44c2:docs/contexto-resumido-templates.md`) e os metadados versionados.

### 4.2 Arquivos criados/modificados no commit `04c44c2`

`git show --name-only 04c44c2` registra:

```text
.gitignore
assets/templates/ATTRIBUTIONS.md
assets/templates/catalog.json
assets/templates/normalized/rectangular_basic.glb
docs/contexto-resumido-templates.md
scripts/blender/normalize_rectangular_basic.py
tests/assets/__init__.py
tests/assets/test_normalized_templates.py
```

Resumo técnico:

- `assets/templates/catalog.json`: catálogo inicial com `id`, categoria, caminho do raw, licença e notas dos candidatos.
- `assets/templates/ATTRIBUTIONS.md`: créditos e licenças dos modelos Sketchfab.
- `assets/templates/normalized/rectangular_basic.glb`: primeiro template final versionado.
- `scripts/blender/normalize_rectangular_basic.py`: primeiro script Blender de normalização, específico para o template retangular.
- `tests/assets/test_normalized_templates.py`: teste de integridade dos GLBs normalizados.
- `.gitignore`: bloqueio de raw assets, `contexto.md` e artefatos de storage.
- `docs/contexto-resumido-templates.md`: resumo de handoff para outra IA; removido posteriormente por `408ef0f`/`f8b3c39`.

### 4.3 Dependências introduzidas

Nenhum pacote Python novo foi adicionado aos `requirements*.txt` nesta sessão.

Dependência externa operacional:

```text
Blender 5.1.1
```

Instalação local feita via `winget`:

```powershell
winget install --id BlenderFoundation.Blender -e
```

Teste headless executado com sucesso durante a sessão:

```text
importar scene.gltf -> exportar GLB temporario -> remover arquivo temporario
```

### 4.4 Validação inicial

O teste criado em `tests/assets/test_normalized_templates.py` estabeleceu um contrato mínimo para templates normalizados:

- arquivo `.glb` válido;
- magic header `glTF`;
- versão glTF 2.0;
- nós obrigatórios;
- material `LabelMaterial`.

Na versão inicial do teste, a convenção ainda tratava `Bottle`, `Cap` e `Label` como obrigatórios. A sessão posterior `historico/2026-04-26_fase2-templates-clip-cor.md` revisou isso: `Cap` tornou-se opcional porque alguns templates do Sketchfab são peça única. Essa revisão é uma modificação importante da decisão inicial.

## 5. Problemas encontrados e soluções

### 5.1 Ambiguidade sobre "instalar templates"

**Problema:** inicialmente havia confusão entre instalar algo no Blender e instalar templates no projeto.

**Diagnóstico:** templates não são plugins do Blender; são assets 3D externos que precisam ser importados, normalizados e exportados para um contrato estável.

**Solução:** definir o fluxo:

```text
baixar modelo -> classificar -> registrar licença -> importar no Blender -> normalizar -> exportar GLB -> versionar template final
```

### 5.2 Classificação de modelos sem renderização visual completa

**Problema:** os modelos baixados tinham nomes genéricos (`perfume_bottle`, `perfume_bottle (1)`, etc.) e estruturas internas heterogêneas.

**Diagnóstico:** foi necessário usar nomes de pastas, metadados `license.txt`, nomes de materiais/nós e dimensões aproximadas dos `scene.gltf` para separar por categoria.

**Solução:** classificação pragmática em cinco famílias (`retangulares_altos`, `cilindricos_ou_altos_redondos`, `quadrados_compactos`, `redondos_esfericos`, `ornamentais_porcelana_antigos`) e uma família `nao_templates`.

### 5.3 Erro operacional no script de movimentação local

**Problema:** a primeira tentativa de criar pastas com `New-Item -LiteralPath` falhou no PowerShell disponível, e `Move-Item` emitiu erros de destino ausente.

**Solução:** repetir a operação usando `New-Item -Path ... -ErrorAction Stop`, verificando caminho absoluto de origem/destino antes de mover. Nenhum diretório saiu do lugar na tentativa falha; a segunda execução moveu corretamente.

### 5.4 `python` indisponível fora do ambiente virtual

**Problema:** a tentativa de inspecionar `.gltf` com `python` falhou:

```text
Python nao foi encontrado
```

**Solução:** usar PowerShell (`ConvertFrom-Json`) para extrair metadados dos `.gltf`. Isso reforçou uma lição operacional: scripts essenciais do projeto devem rodar no `.venv` do backend ou declarar claramente o interpretador.

### 5.5 Risco de commitar binários intermediários

**Problema:** o VS Code mostrava muitos arquivos não rastreados, incluindo `scene.bin`, texturas `.png` e raw assets grandes.

**Solução:** bloquear `assets/templates/raw/` no `.gitignore` e recomendar commit apenas de:

```text
assets/templates/ATTRIBUTIONS.md
assets/templates/catalog.json
assets/templates/normalized/*.glb
docs/contexto-resumido-templates.md   # enquanto existia
```

O resumo `docs/contexto-resumido-templates.md` foi posteriormente removido por limpeza documental; o conteúdo relevante passa a ser preservado neste `historico/`.

## 6. Conceitos teóricos envolvidos

- **Fotogrametria SfM vs. modelagem baseada em templates.** Meshroom/AliceVision implementa reconstrução por correspondência de features entre imagens. Para vidro e reflexos, features não são estáveis entre ângulos. Templates trocam reconstrução literal por representação paramétrica controlada.
- **Curadoria de dataset/asset.** Modelos 3D externos não são homogêneos: variam em licença, topologia, escala, orientação, materiais, presença de label e separação entre corpo/tampa/líquido. A curadoria é parte do método, não tarefa secundária.
- **Licenciamento Creative Commons.** `CC-BY` exige atribuição; `CC0` dispensa obrigação, mas registro é desejável. Licenças `ND` conflitam com derivados. Esse ponto é relevante para qualquer artigo ou TCC com assets externos.
- **GLTF/GLB como formato de interoperabilidade.** `scene.gltf + scene.bin + textures/` representa a versão textual/externa; `.glb` empacota JSON, buffers e imagens em um binário único, mais conveniente para servir ao app.
- **Blender headless.** Permite usar o Blender como etapa automatizada de pipeline (`--background --python`), sem intervenção manual constante, mantendo compatibilidade com materiais PBR e exportação glTF.
- **Contrato de assets.** Nomear nós como `Bottle`, `Cap`, `Liquid`, `Label` transforma um arquivo artístico em componente programável. A estabilidade dos nomes permite que scripts posteriores apliquem cor, material e textura.
- **Versionamento de binários.** Git comum lida mal com assets 3D grandes e diffs binários. A decisão de ignorar raw assets e versionar apenas finais reduz peso do histórico, mas cria dependência de fontes externas.

## 7. Pendências e próximos passos

### 7.1 Pendências anteriores revisitadas

Não havia arquivo anterior em `historico/` para a Fase 1. A pendência anterior foi inferida do `README.md` do commit `0106a1f`:

| Pendência anterior | Estado nesta sessão |
|---|---|
| Integrar Meshroom/AliceVision como Fase 2. | 🔄 **Modificada/substituída.** O caminho principal passou a ser Blender + templates por incompatibilidade empírica entre SfM e frascos translúcidos/reflexivos. Meshroom permanece como evidência metodológica e alternativa discutida, mas não como implementação principal. |
| Converter `.obj` → `.glb` via Blender headless. | 🔄 **Modificada.** Blender headless continua central, mas a conversão inicial agora parte de templates `.gltf/.glb` do Sketchfab, não de `.obj` produzido pelo Meshroom. |
| Feature flag `PROCESSOR_TYPE=fake|meshroom`. | 🔄 **Substituída.** A evolução posterior usará `PROCESSOR_TYPE=fake|template` e, mais tarde, `hunyuan` como alternativa IA. |
| Progresso granular do pipeline de fotogrametria. | ❌ **Abandonada nesta fase.** Sem Meshroom no caminho principal, o progresso granular por nós AliceVision deixa de ser prioridade. |

Os arquivos já existentes em `historico/` foram lidos, mas pela cronologia Git eles são posteriores a esta sessão. Assim, suas pendências não são herdadas aqui; elas são consequências do trabalho que começa nesta preparação.

### 7.2 Pendências geradas por esta sessão

1. **Normalizar os demais templates.** `04c44c2` só entrega `rectangular_basic.glb`. Os demais (`cylindrical_basic`, `square_compact`, `round_spherical`, `ornamental_modernist`) foram entregues depois em `57766a1`.
2. **Generalizar o script de normalização.** `normalize_rectangular_basic.py` era específico demais; `fd70010` resolve posteriormente com `normalize_template.py` e registry por template.
3. **Implementar o `TemplateProcessor`.** Necessário para usar os GLBs normalizados no fluxo real de captura. Resolvido posteriormente em `f073dbb`.
4. **Atualizar documentação pública.** O README do backend ainda falava em Meshroom como Fase 2; documentos posteriores alinharam melhor o backend ao código (`26799cf`), mas o README raiz ainda pode permanecer parcialmente desatualizado. [verificar]
5. **Definir política final de assets grandes.** A sessão escolheu ignorar raw assets; ainda falta decidir se templates finais grandes devem entrar em Git comum, Git LFS ou pacote externo.
6. **Preservar histórico da decisão.** `docs/contexto-resumido-templates.md` foi removido depois; este arquivo de `historico/` passa a cumprir esse papel.

## 8. Reflexão para o TCC

Esta sessão é pequena em volume de código, mas grande em significado metodológico. Ela marca a passagem de uma visão inicial baseada em reconstrução fotogramétrica para uma abordagem mais adequada ao domínio observado empiricamente. O resultado não foi "desistir de 3D", mas escolher uma forma de modelagem 3D mais controlável para frascos de perfume.

O ponto acadêmico central é que a mudança de direção não nasceu de preferência estética: nasceu de um experimento negativo com Meshroom. Frascos translúcidos e reflexivos expõem uma limitação clássica de SfM; templates paramétricos respondem a essa limitação com previsibilidade, menor tempo de processamento e maior controle visual. Para o TCC, essa é uma justificativa metodológica forte.

A sessão também introduz uma camada frequentemente invisível em projetos acadêmicos: governança de assets. Escolher modelos não é apenas baixar arquivos bonitos. É verificar licença, registrar autoria, evitar marcas conhecidas no produto final, controlar peso no Git e transformar arquivos artísticos em componentes com contrato programável.

Por fim, a decisão de versionar um primeiro `rectangular_basic.glb` antes de escrever todo o pipeline mostra uma prática saudável: provar o elo mais incerto primeiro. Sem um template normalizado real, `TemplateProcessor`, CLIP e detector de cor seriam abstrações sem substrato visual. A sessão posterior de Fase 2 se apoia diretamente nessa prova mínima.

---

*Documento gerado em 2026-05-09 a partir da conversa da sessão, inspeção direta do working tree, leitura de todos os arquivos em `historico/` e ancoragem pelo Git (`git log --all --pretty=format:"%h %ad %s" --date=short`). Quando houve divergência entre documento e Git, o Git foi priorizado.*
