# Build

## Visao geral

O diretorio raiz `build/` existe no estado atual e contem uma arvore `build/app/intermediates/flutter/debug/flutter_assets/...`, sem arquivos listados durante a exploracao read-only. Isso indica artefato intermediario de build Flutter/Android, mas o comando exato que o gerou esta `⚠️ a confirmar` (fonte: `build/`).

## Por que existe

`build/` e usado por ferramentas de build para armazenar saidas intermediarias ou finais. No contexto deste projeto, o padrao de caminhos aponta para Flutter/Gradle Android (`app/intermediates/flutter/debug/flutter_assets`) (fontes: `build/`, `front/android/app/build.gradle.kts`, `front/pubspec.yaml`).

## Stack/dependencias

| Origem provavel | Evidencia | Fontes |
|---|---|---|
| Flutter | `flutter_assets` e dependencias declaradas no app | `build/`, `front/pubspec.yaml` |
| Android/Gradle | `app/intermediates` e configuracao Android Flutter | `build/`, `front/android/app/build.gradle.kts` |
| Assets de pacotes | Subpastas esperadas como `packages/model_viewer_plus` quando artefatos existem | `build/`, `front/pubspec.yaml` |

Nao ha Dockerfile ou script no repositorio que gere `C:\TCC\build` diretamente; o gerador exato permanece `⚠️ a confirmar` (fontes: `docker-compose.yml`, `front/pubspec.yaml`, `back/requirements.txt`).

## Estrutura

Estado observado:

```text
build/
  app/
    intermediates/
      flutter/
        debug/
          flutter_assets/
            fonts/
            packages/
            shaders/
```

Durante a exploracao, nao foram encontrados arquivos dentro de `build/`, apenas diretorios (fonte: `build/`).

## Como rodar/usar

Nao edite `build/` manualmente. Para regenerar artefatos Flutter, use comandos Flutter a partir de `front/` quando necessario:

```powershell
cd C:\TCC\front
flutter build apk
flutter build web
flutter build windows
```

Para limpar artefatos do Flutter, o comando usual e:

```powershell
cd C:\TCC\front
flutter clean
```

Esses comandos devem ser executados somente quando a equipe quiser regenerar artefatos; esta documentacao nao executou builds nem limpou artefatos (fontes: `front/pubspec.yaml`, `front/android/app/build.gradle.kts`).

## Pontos de atencao

- O usuario pediu explicitamente para nao modificar `build/`; esta documentacao trata `build/` como leitura/artefato (fonte: pedido do usuario e caminho `build/`).
- O comando exato que criou `C:\TCC\build` esta `⚠️ a confirmar`, porque nao ha manifest dedicado na raiz que descreva esse artefato (fontes: `front/pubspec.yaml`, `docker-compose.yml`, `back/requirements.txt`).
- Se o objetivo for versionar releases, defina antes qual alvo e oficial: Android APK/AAB, Web, Windows ou outro `⚠️ a confirmar` (fontes: `front/android/app/build.gradle.kts`, `front/web/index.html`, `front/windows/runner/main.cpp`).

