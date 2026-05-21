# Setup de Worktrees para Benchmark

## Por que worktree

Cada branch (`Blander`, `Meshroom`, `IA`) tem implementação distinta do
pipeline 3D. Não dá pra importar tudo no mesmo processo Python. Worktree
permite ter as 3 branches **simultaneamente** em diretórios separados,
compartilhando o `.git` mas cada uma com seu próprio venv, deps e código.

## Layout (estrutura final do disco)

> ⚠️ **Importante**: o repositório git é o **`back/`** — não há nesting.
> `C:\TCC\` é apenas uma pasta-mãe contendo o `back/` (repo), o `front/`
> (outro repo Flutter), `docker/`, etc.

```
C:\TCC\                    ← pasta-mãe (NÃO é repo git)
├── back\                  ← worktree principal (branch IA) — É o repo git
│   ├── run_benchmark.py
│   ├── eval/
│   └── ...
├── front\                 ← repo Flutter (independente)
├── docker\
└── TCC_eval_data\         ← dataset compartilhado (fora de qualquer repo git)
    ├── held_out\
    │   ├── manifest.json
    │   └── *.glb
    ├── synthetic_views\
    ├── outputs\
    │   ├── blander\<id>.glb
    │   ├── meshroom\<id>.glb
    │   └── ia\<id>.glb
    └── results.csv

C:\TCC_blander\            ← worktree branch Blander (cópia completa de back/)
├── run_benchmark.py
├── eval/                  ← terá quando a branch Blander tiver merge dessas mudanças
├── .venv\                 ← venv próprio
└── ...

C:\TCC_meshroom\           ← worktree branch Meshroom (mesmo padrão)
└── ...
```

## Por que `TCC_eval_data\` está dentro de `C:\TCC\`?

Por escolha do projeto. Tecnicamente `C:\TCC_eval_data\` (top-level) seria
mais "puro" porque ficaria neutro entre worktrees, mas a equipe preferiu
manter tudo agrupado em `C:\TCC\`. Como o repo git é o `back/`, o
`TCC_eval_data/` continua **fora do git** mesmo dentro de `C:\TCC\` —
sem risco de commit acidental, sem precisar de `.gitignore`.

Implicação prática: as worktrees Blander/Meshroom (que ficam em
`C:\TCC_blander\` e `C:\TCC_meshroom\`, fora de `C:\TCC\`) precisam da
env var `TCC_EVAL_DATA_ROOT` apontando pra cá:

```powershell
$env:TCC_EVAL_DATA_ROOT = "C:\TCC\TCC_eval_data"
```

(Documento `RUN_BENCHMARK_CONTRACT.md` orienta cada `run_benchmark.py` a
respeitar essa variável.)

## Comandos para criar as worktrees

Dentro de `C:\TCC\back\` (a worktree IA):

```powershell
# Cria worktree para a branch Blander
cd C:\TCC\back
git worktree add C:\TCC_blander Blander

# Cria worktree para a branch Meshroom
git worktree add C:\TCC_meshroom Meshroom

# Conferir
git worktree list
```

Saída esperada:

```
C:/TCC/back     <commit>  [IA]
C:/TCC_blander  <commit>  [Blander]
C:/TCC_meshroom <commit>  [Meshroom]
```

## Setup do venv em cada worktree

Cada branch tem deps diferentes — **cada worktree precisa do seu próprio
venv**. Não compartilhe!

### `C:\TCC_blander\` (branch Blander)

```powershell
cd C:\TCC_blander
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
# Confere que Blender está no PATH e BLENDER_EXECUTABLE está no .env
```

### `C:\TCC_meshroom\` (branch Meshroom)

```powershell
cd C:\TCC_meshroom
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
# Configura caminho do Meshroom no .env da branch
```

### `C:\TCC\back\` (branch IA) — já configurado

Confira que o `run_benchmark.py` está em `back/`:

```powershell
ls C:\TCC\back\run_benchmark.py
```

## Próximo passo por branch

Cada uma das outras duas branches (Blander, Meshroom) precisa ter um
`run_benchmark.py` (no root da worktree) com a interface CLI documentada
em [RUN_BENCHMARK_CONTRACT.md](./RUN_BENCHMARK_CONTRACT.md).

Quando isso estiver feito, rode (na worktree IA):

```powershell
cd C:\TCC\back
.\.venv\Scripts\activate
python -m eval.benchmark --branches IA Blander Meshroom
```

E o `results.csv` aparece em `C:\TCC\TCC_eval_data\results.csv`.

## Atualizar deps de cada worktree

```powershell
# Em cada worktree, ative o venv e dê pull
cd C:\TCC_blander
git pull origin Blander
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## Remover uma worktree

```powershell
cd C:\TCC\back
git worktree remove C:\TCC_blander
```

Os arquivos da worktree são apagados, mas a branch Blander continua
intacta no git remoto.

## Cuidados

- **Não trabalhe no mesmo arquivo nas duas worktrees simultaneamente** —
  cada uma tem seu próprio working tree, mas o histórico é compartilhado.
- **Commits em uma worktree aparecem no `git log` da outra** após pull.
- **`.venv` é por worktree** — está no `.gitignore`, então não é
  versionado. Cada worktree precisa criar o seu.
- **Cuidado com `git clean -fdx` em `C:\TCC\back\`**: como `TCC_eval_data\`
  está em `C:\TCC\` (fora do repo git), está protegido — mas evite mesmo
  assim, principalmente se trabalhar com `core.untrackedCache`.
