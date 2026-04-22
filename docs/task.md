# Tarefa técnica — Implementar o fluxo 3D funcional ponta a ponta no projeto `perfume_3d_mvp`

Você é um engenheiro de software sênior com experiência em Flutter, FastAPI, integração com pipelines de processamento assíncrono e visualização 3D. Sua tarefa é **pegar o repositório existente e deixar o fluxo 3D funcional ponta a ponta**, com foco no MVP acadêmico.

## 1. Contexto do projeto

O projeto `perfume_3d_mvp` já existe e já possui:
- app Flutter estruturado em `Feature-First + Clean Architecture`;
- gerenciamento de estado com Riverpod;
- navegação com go_router;
- feature de captura guiada (`product_capture`);
- feature de processamento (`processing`);
- feature de visualização 3D (`product_viewer`);
- contrato esperado do backend documentado. 

A jornada do usuário já está definida como:
1. Home
2. Intro de captura
3. Captura guiada
4. Revisão das imagens
5. Processamento
6. Visualização 3D

O app **não reconstrói o 3D no celular**. Ele apenas:
- captura imagens,
- envia ao backend,
- recebe um `jobId`,
- faz polling do status,
- e exibe um `.glb`/`.gltf` retornado pelo backend.

### Decisão arquitetural
- o app Flutter será o cliente;
- o backend será um único serviço FastAPI;
- o banco será PostgreSQL único;
- o armazenamento será local no MVP;
- o processamento 3D será executado por um worker/processo local assíncrono integrado ao backend.

### Restrições
- não dividir o backend em microsserviços;
- não criar múltiplos bancos;
- não criar uma arquitetura distribuída complexa para o MVP;
- preservar organização modular interna no backend.

## 2. Objetivo desta tarefa

Deixar **o fluxo 3D funcional**, priorizando a parte de modelagem/visualização 3D antes de qualquer módulo financeiro.

O objetivo é que o seguinte cenário funcione de verdade:

1. usuário tira ou seleciona imagens;
2. app envia imagens para o backend;
3. backend recebe e registra o job;
4. backend processa (ou simula o processamento na primeira fase);
5. endpoint de status responde corretamente;
6. quando concluído, o backend devolve `modelUrl`;
7. o app abre a tela de visualização e carrega o modelo 3D com rotação e zoom.

## 3. Regra principal de implementação

**Não redesenhe a arquitetura existente.**  
A estrutura do projeto já está definida e documentada. Você deve **trabalhar em cima da base atual**, aproveitando:
- `product_capture`
- `processing`
- `product_viewer`
- `core/network`
- `app/router`
- os providers Riverpod já previstos
- o contrato de backend já documentado

Se algum ajuste for necessário, faça ajustes pontuais, não uma reescrita geral.

## 4. Stack e decisões obrigatórias

### Front-end
Usar o que já está no projeto:
- Flutter
- Riverpod
- go_router
- dio
- camera
- image_picker
- sensors_plus
- opencv_dart
- model_viewer_plus

### Back-end
Implementar com:
- FastAPI
- Python
- armazenamento local em disco
- jobs assíncronos simples
- endpoint HTTP compatível com o app

### Banco
Usar:
- PostgreSQL

### Visualização 3D
Usar:
- `model_viewer_plus`
- arquivos `.glb` ou `.gltf`

### Processamento 3D
Fase 1:
- pode usar processamento fake/simulado, desde que o fluxo completo funcione

Fase 2:
- preparar o backend para integrar com pipeline real de reconstrução 3D (Meshroom/AliceVision ), mas sem travar a entrega do MVP funcional

## 5. Prioridade absoluta

A prioridade é deixar **funcional o caminho crítico do fluxo 3D**:

- upload de imagens
- criação de `jobId`
- polling de status
- retorno de `modelUrl`
- abertura do visualizador 3D com um modelo carregável

Não priorize agora:
- sistema financeiro
- notificações financeiras
- ranking de pagadores
- histórico comercial completo

Esses módulos existem no projeto maior, mas **não são o foco desta implementação agora**.

## 6. O que deve ser implementado no backend

Implemente um backend mínimo funcional com estes endpoints:

### `POST /captures`
Responsabilidades:
- aceitar `multipart/form-data` com `images[]`
- validar recebimento mínimo
- salvar arquivos localmente
- criar um `jobId`
- registrar job no banco ou, no mínimo, em estrutura persistente local
- devolver:
```json
{
  "jobId": "..."
}