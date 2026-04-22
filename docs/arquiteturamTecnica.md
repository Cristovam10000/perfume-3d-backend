# Arquitetura Técnica do Projeto
## Sistema de Gestão de Vendas, Cobranças e Vitrine 3D

## 1. Visão geral

O projeto consiste em um sistema com dois núcleos principais:

1. **núcleo comercial e financeiro**, responsável por cadastro de clientes, produtos, vendas, parcelas, pagamentos, eventos de parcela, notificações e resumo financeiro do cliente;
2. **núcleo de vitrine 3D**, responsável por captura guiada de imagens de produtos, envio para um backend externo, processamento fotogramétrico e visualização do modelo 3D final no aplicativo.

A proposta central é permitir que o aplicativo mobile oriente a captura de imagens de produtos, especialmente perfumes, envie essas imagens para processamento externo e, ao mesmo tempo, sirva como sistema de apoio à gestão das vendas parceladas.

---

## 2. Arquitetura geral da solução

A arquitetura do sistema é composta por cinco camadas principais:

### 2.1 Aplicativo mobile
Responsável por:
- orientar o usuário durante a captura das imagens;
- analisar qualidade básica da captura em tempo real;
- enviar as imagens ao backend;
- acompanhar o status do processamento;
- exibir o modelo 3D final no aplicativo.

### 2.2 Backend HTTP
Responsável por:
- receber as imagens enviadas pelo aplicativo;
- criar e gerenciar um job de processamento;
- registrar o estado do job;
- devolver o status do processamento ao app;
- publicar ou informar a URL do modelo 3D final.

### 2.3 Pipeline de reconstrução 3D
Responsável por:
- executar fotogrametria a partir do conjunto de imagens;
- gerar o modelo tridimensional do produto;
- exportar o resultado em formato adequado para visualização no app.

### 2.4 Armazenamento
Responsável por:
- guardar as imagens de entrada;
- guardar o modelo 3D final;
- guardar arquivos auxiliares, como preview e saídas intermediárias, se necessário.

### 2.5 Banco de dados
Responsável por:
- persistir metadados do sistema;
- armazenar dados de clientes, produtos, vendas e cobranças;
- registrar caminhos dos arquivos 3D;
- manter histórico operacional e financeiro.

---

## 3. Arquitetura do front-end

O front-end foi definido em **Flutter**, com organização baseada em:

- **Feature-First**;
- **Clean Architecture**;
- **Riverpod** para gerenciamento de estado e injeção de dependências.

### 3.1 Stack do front-end
- Flutter
- Dart
- flutter_riverpod
- go_router
- dio
- camera
- image_picker
- sensors_plus
- opencv_dart
- model_viewer_plus
- Material 3

### 3.2 Papel de cada tecnologia no front-end

#### Flutter + Dart
Base do aplicativo mobile multiplataforma.

#### flutter_riverpod
Usado para gerenciamento de estado, controllers e dependências.

#### go_router
Usado para navegação entre as telas do fluxo principal.

#### dio
Usado para comunicação HTTP com o backend, incluindo upload das imagens e consulta de status.

#### camera
Usado para abertura da câmera e captura guiada em tempo real.

#### image_picker
Usado como suporte para seleção de imagens da galeria.

#### sensors_plus
Usado para leitura do acelerômetro e análise de inclinação do aparelho.

#### opencv_dart
Usado para análise de imagem no app, especialmente comparação de frames, rastreamento de similaridade e apoio à captura guiada.

#### model_viewer_plus
Usado para exibir o arquivo `.glb` ou `.gltf` no aplicativo com rotação, zoom e interação visual.

### 3.3 Organização por features
O front-end está dividido nas seguintes features principais:
- `home`
- `product_capture`
- `processing`
- `product_viewer`

### 3.4 Fluxo principal do front-end
1. Tela inicial
2. Tela de instruções de captura
3. Tela de captura guiada
4. Tela de revisão das imagens
5. Tela de processamento
6. Tela de visualização 3D

---

## 4. Arquitetura da captura guiada

A captura guiada é uma das partes mais importantes do sistema.

O aplicativo não apenas tira fotos, mas orienta o usuário a produzir um conjunto de imagens adequado para reconstrução 3D.

### 4.1 Funções da captura guiada
- verificar se há imagens suficientes;
- avaliar brilho, nitidez e saturação;
- verificar inclinação do celular;
- comparar visualmente o frame atual com imagens já capturadas para evitar ângulos repetidos;
- emitir avisos sobre iluminação, repetição de ângulo, enquadramento e qualidade.

### 4.2 Utilitários técnicos previstos
- `frame_analyzer`
- `image_quality_analyzer`
- `orb_similarity_tracker`
- `tilt_tracker`

### 4.3 Objetivo da captura guiada
Aumentar a qualidade do conjunto de imagens enviado ao backend, reduzindo falhas no pipeline fotogramétrico.

---

## 5. Arquitetura do backend

O backend é um serviço externo ao aplicativo Flutter.

Ele não precisa ser executado dentro do app, mas deve estar acessível via HTTP.

### 5.1 Responsabilidades do backend
- receber o lote de imagens;
- criar um identificador de processamento (`jobId`);
- armazenar as imagens;
- disparar o pipeline de reconstrução 3D;
- acompanhar o job;
- expor o status ao aplicativo;
- devolver a URL do modelo final.

### 5.2 Endpoints mínimos

#### `POST /captures`
Responsável por:
- receber imagens em multipart/form-data;
- iniciar o processamento;
- retornar um `jobId`.

#### `GET /captures/{jobId}/status`
Responsável por:
- informar o status atual do processamento;
- retornar progresso, mensagem e URL do modelo final quando concluído.

### 5.3 Backend mínimo funcional
O backend deve suportar, no mínimo, os estados:
- `queued`
- `processing`
- `uploading`
- `completed`
- `failed`

---

## 6. Stack da modelagem 3D

A modelagem 3D do projeto deve ser entendida em duas partes:

### 6.1 No aplicativo
O aplicativo **não reconstrói o modelo 3D**.

Ele apenas:
- orienta a captura;
- envia imagens;
- recebe o resultado;
- exibe o modelo final.

### 6.2 No backend/pipeline externo
A reconstrução 3D será feita por um pipeline de **fotogrametria**.

A stack escolhida para isso é:
- **Meshroom / AliceVision**

### 6.3 Papel do Meshroom / AliceVision
- receber o conjunto de imagens;
- processar a fotogrametria;
- gerar malha e textura;
- exportar o modelo final em formato compatível com o app.

### 6.4 Formato final esperado
- `.glb`
- `.gltf`

### 6.5 Visualização no app
O modelo final será exibido com:
- `model_viewer_plus`
- rotação
- zoom
- controles de câmera

---

## 7. Armazenamento

### 7.1 Estratégia definida para o MVP acadêmico
Para o MVP acadêmico, o armazenamento será **local**.

Isso significa que os arquivos serão guardados na máquina onde o backend/pipeline estiver rodando.

### 7.2 O que será armazenado localmente
- imagens capturadas enviadas pelo app;
- arquivos gerados do modelo 3D;
- imagens de preview;
- arquivos intermediários do processamento, se necessário.

### 7.3 O que o banco guarda
O banco não guarda o arquivo em si. Ele guarda:
- metadados;
- caminhos dos arquivos;
- status;
- vínculos entre produto e modelo 3D.

### 7.4 Evolução futura
Em uma evolução futura, o armazenamento poderá migrar para:
- Amazon S3
- Firebase Storage
- outro serviço de object storage

Mas isso não é obrigatório no MVP acadêmico.

---

## 8. Banco de dados

### 8.1 Banco escolhido
- **PostgreSQL**

### 8.2 Ferramenta de administração
- **DBeaver**

### 8.3 Papel do banco no sistema
O PostgreSQL será usado para armazenar:
- clientes;
- produtos;
- modelos 3D dos produtos;
- vendas;
- itens da venda;
- parcelas;
- pagamentos;
- eventos de parcela;
- notificações;
- resumo financeiro do cliente.

### 8.4 Arquivos não ficam no banco
As imagens e os arquivos `.glb` não ficam armazenados diretamente nas tabelas. O banco apenas registra o caminho do arquivo e seus metadados.

---

## 9. Arquitetura da parte comercial e financeira

Além da vitrine 3D, o sistema possui um núcleo comercial/financeiro mais robusto.

### 9.1 Entidades principais
- `clientes`
- `produtos`
- `modelos_3d_produto`
- `vendas`
- `itens_venda`
- `parcelas`
- `pagamentos`
- `eventos_parcela`
- `notificacoes`
- `resumo_financeiro_cliente`

### 9.2 Regras principais já definidas
- um cliente pode fazer várias compras;
- uma venda pode ter vários produtos;
- a venda pode ter entrada;
- o parcelamento pertence à venda inteira;
- parcelas podem receber pagamentos parciais;
- o sistema mantém histórico de atrasos e renegociações;
- o sistema mantém histórico de notificações;
- o sistema mantém um resumo financeiro por cliente;
- o modelo 3D pertence ao produto, não à venda.

---

## 10. Fluxo completo do sistema

### 10.1 Fluxo de vitrine 3D
1. usuário abre o app;
2. recebe instruções;
3. captura várias imagens do produto;
4. revisa as imagens;
5. envia para o backend;
6. backend cria um job;
7. pipeline 3D processa as imagens;
8. backend publica o `.glb`;
9. app consulta o status;
10. app abre o visualizador 3D.

### 10.2 Fluxo comercial/financeiro
1. cadastrar cliente;
2. cadastrar produto ou criar produto durante a venda;
3. registrar venda com vários itens;
4. registrar entrada;
5. gerar parcelas;
6. registrar pagamentos;
7. registrar atrasos e eventos;
8. gerar notificações;
9. atualizar resumo financeiro do cliente.

---

## 11. Ambiente de desenvolvimento local

### 11.1 Aplicativo
- Flutter rodando em emulador ou dispositivo físico

### 11.2 Backend
- serviço local acessível por HTTP

### 11.3 Banco
- PostgreSQL local

### 11.4 Processamento 3D
- pipeline Meshroom / AliceVision rodando localmente

### 11.5 Endereço do backend
Em ambiente local Android, o app pode apontar para:
- `http://10.0.2.2:8000` no emulador Android
- `http://<IP-da-maquina>:8000` em dispositivo físico na mesma rede

---

## 12. Resumo técnico consolidado

A arquitetura do projeto pode ser resumida assim:

- **front-end mobile:** Flutter + Riverpod + go_router + camera + dio + OpenCV + model_viewer_plus;
- **backend HTTP:** serviço externo responsável por upload, job, status e entrega do modelo;
- **pipeline 3D:** Meshroom / AliceVision para fotogrametria;
- **armazenamento:** local no MVP acadêmico;
- **banco de dados:** PostgreSQL;
- **administração do banco:** DBeaver;
- **visualização 3D:** arquivo `.glb` ou `.gltf` renderizado no app.

---

## 13. Conclusão

O projeto foi arquitetado para separar claramente:
- a captura guiada no app;
- o processamento pesado no backend;
- o armazenamento local dos arquivos;
- a persistência relacional no PostgreSQL;
- e a exibição final do modelo 3D no aplicativo.

Essa separação torna o sistema mais viável tecnicamente, mais escalável conceitualmente e mais adequado ao contexto de um MVP acadêmico.
