# Contexto resumido para continuidade por outra IA

Data do resumo: 2026-04-26

## Visao geral do projeto

Este projeto e um TCC com:

- Front-end em Flutter em `C:\TCC\front`.
- Back-end em FastAPI em `C:\TCC\back`.
- Objetivo principal atual: fluxo de vitrine/modelo 3D para perfumes.

O fluxo do app e:

1. Usuario captura ou seleciona imagens no Flutter.
2. Flutter envia as imagens para o backend.
3. Backend cria um `jobId`.
4. App consulta status por polling.
5. Backend retorna `modelUrl`.
6. Flutter carrega o `.glb` no visualizador 3D.

## Estado atual do backend

O backend ja tem a Fase 1 funcional com processamento fake:

- FastAPI.
- SQLAlchemy async.
- PostgreSQL.
- Storage local.
- Fila `asyncio.Queue` in-process.
- Worker interno.
- `FakeProcessor` que gera um `.glb` sintetico.
- Endpoints:
  - `POST /captures`
  - `GET /captures/{jobId}/status`
  - `GET /health`
  - `/files/*` para servir arquivos estaticos.
- Testes automatizados com pytest.
- Script de smoke test.
- README do backend.

Repositorio remoto do backend:

```text
https://github.com/Cristovam10000/back.git
```

Observacao: o arquivo `C:\TCC\back\contexto.md` e um historico grande e esta como untracked. Nao deve ser commitado automaticamente.

## Decisao tecnica recente

O plano antigo era usar Meshroom/AliceVision para fotogrametria real.

Depois de testes praticos com frascos de perfume, a decisao mudou:

- Meshroom funcionou tecnicamente, mas teve resultado ruim para frascos de vidro/reflexivos.
- O problema vem de transparencia, reflexos, superficies lisas e pouca textura estavel.
- A nova abordagem principal e usar templates 3D preexistentes customizados via Blender.

Portanto, a proxima fase deve trocar o foco de `MeshroomProcessor` para `TemplateProcessor`.

Termo recomendado para o TCC:

```text
modelagem 3D parametrica baseada em templates
```

ou:

```text
customizacao programatica de modelos base com Blender
```

## Blender

Blender foi instalado via `winget`.

Executavel validado:

```text
C:\Program Files\Blender Foundation\Blender 5.1\blender.exe
```

Versao validada:

```text
Blender 5.1.1
```

O comando `blender` pode nao estar no PATH. Preferir usar o caminho absoluto acima.

Foi feito um teste headless com sucesso:

- Importou `scene.gltf`.
- Exportou `.glb`.
- O arquivo temporario de smoke foi removido depois.

## Modelos baixados do Sketchfab

Os modelos originais estavam em:

```text
C:\teste-images
```

Eles foram separados fisicamente em:

```text
C:\teste-images\_classificados
```

Classificacao atual:

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

`imagens` sao fotos de captura.
`novo.mg` e cache/projeto do Meshroom.
Ambos nao sao templates.

## Templates copiados para o backend

Foi copiado um conjunto pequeno de candidatos para:

```text
C:\TCC\back\assets\templates\raw
```

Estrutura atual:

```text
raw\
  rectangular\
    rectangular_basic
    rectangular_modern_reference

  cylindrical\
    cylindrical_basic

  square\
    square_compact

  round\
    round_spherical

  ornamental\
    ornamental_modernist
```

Arquivos criados:

```text
C:\TCC\back\assets\templates\catalog.json
C:\TCC\back\assets\templates\ATTRIBUTIONS.md
```

`catalog.json` registra os templates brutos e suas categorias.
`ATTRIBUTIONS.md` registra autores, links e licencas.

## Licencas

Regra adotada:

- `CC0`: pode usar sem credito obrigatorio, mas ainda e bom registrar.
- `CC-BY-4.0`: pode usar e modificar, mas precisa creditar autor e link.
- Licencas com `ND`: nao usar para templates, pois nao permitem derivados.
- `Editorial`: nao usar.
- `Standard`/`Free Standard`: evitar por enquanto para simplificar o TCC.

Modelos atuais no backend:

- `rectangular_basic`: CC-BY-4.0, autor lamborado.
- `rectangular_modern_reference`: CC-BY-4.0, autor oddphi5h. Contem marca conhecida; usar apenas como referencia visual, nao como template final do produto.
- `cylindrical_basic`: CC-BY-4.0, autor Mgabrov.
- `square_compact`: CC-BY-4.0, autor Ahani Digital Solution.
- `round_spherical`: CC-BY-4.0, autor milaha.
- `ornamental_modernist`: CC0-1.0, autor Virtual Museums of Malopolska.

## Proximo passo recomendado

Normalizar os templates no Blender.

Comecar por:

```text
C:\TCC\back\assets\templates\raw\rectangular\rectangular_basic\scene.gltf
```

Abrir no Blender:

```text
File > Import > glTF 2.0
```

Depois padronizar objetos importantes com nomes estaveis:

```text
Bottle
Liquid
Cap
Label
```

Se o modelo nao tiver `Label`, criar uma placa fina na frente do frasco para receber textura do rotulo.

Exportar templates normalizados para:

```text
C:\TCC\back\assets\templates\normalized
```

Exemplo esperado:

```text
C:\TCC\back\assets\templates\normalized\rectangular_basic.glb
```

## Proxima fase de codigo

Depois que pelo menos um template normalizado existir, implementar:

1. `TemplateProcessor`, mantendo a interface atual `Processor`.
2. Script Blender Python, provavelmente em `app/modules/captures/blender_scripts/`.
3. Configuracao no `.env`:

```text
PROCESSOR_TYPE=fake|template
BLENDER_EXECUTABLE=C:\Program Files\Blender Foundation\Blender 5.1\blender.exe
```

4. Backend deve chamar Blender headless:

```text
blender.exe --background --python customize_template.py -- <args>
```

5. O script deve:
   - carregar o template normalizado `.glb`;
   - aplicar parametros basicos;
   - opcionalmente aplicar imagem de rotulo;
   - exportar `storage/models/<jobId>.glb`.

## Observacoes importantes

- Nao reintroduzir Meshroom como caminho principal agora.
- Meshroom pode ser citado no TCC como experimento/justificativa metodologica.
- A arquitetura atual ja foi pensada para trocar processadores sem reescrever router/service/queue.
- O `README.md` ainda pode estar desatualizado ao falar em Meshroom como Fase 2. Deve ser revisado depois para refletir Blender + templates.
- Evitar commitar arquivos grandes ou temporarios de `storage/`.
- Avaliar se os templates raw devem entrar no Git; eles somam aproximadamente 113 MB.
