# Hz Power Switcher

App Windows simples para:

- alternar automaticamente a frequência do ecrã quando o carregador é ligado ou desligado
- escolher qualquer valor de Hz que o Windows reconheça para o ecrã selecionado
- arrancar com o Windows
- arrancar minimizada
- ficar minimizada na bandeja do sistema

## O que está incluído

- `hz_power_switcher.py` — app principal
- `hz_power_switcher.ico` — ícone simples inspirado em Hz
- `requirements.txt` — dependências
- `build_exe.bat` — exemplo de build para `.exe` com PyInstaller

## Requisitos

- Windows 10 ou 11
- Python 3.11+ recomendado
- Dependências:
  - `pystray`
  - `Pillow`

## Instalação rápida

```powershell
pip install -r requirements.txt
python hz_power_switcher.py
```

## Gerar `.exe`

Primeiro instala o PyInstaller:

```powershell
pip install pyinstaller
```

Depois executa:

```powershell
build_exe.bat
```

O executável ficará em `dist\HzPowerSwitcher.exe`.

## Como funciona

- a app lê os ecrãs ativos do Windows
- para o ecrã selecionado, lista as frequências reconhecidas pelo sistema para a resolução atual
- guarda duas frequências:
  - uma para corrente
  - uma para bateria
- monitoriza o estado de alimentação em ciclo simples
- quando o estado muda, aplica a frequência correspondente

## Observações

- a lista de Hz depende do que o Windows e o driver gráfico expõem nesse momento
- se um valor não aparecer, o sistema não o está a disponibilizar para a resolução atual
- em alguns equipamentos, a alteração pode falhar por limitações do driver ou do painel
- se usares monitor externo, convém confirmar qual o ecrã alvo selecionado

## Ficheiros gerados pela app

A app cria a sua configuração em:

```text
%LOCALAPPDATA%\HzPowerSwitcher\
```

Normalmente vais encontrar:

- `config.json`
- `app.log`

## Arranque com o Windows

Quando ativas esta opção, a app cria uma entrada em:

```text
HKCU\Software\Microsoft\Windows\CurrentVersion\Run
```

## Nota prática

A arquitetura foi mantida simples de propósito:

- sem serviço Windows
- sem tarefa agendada
- sem módulo externo para DisplayConfig
- sem consola visível quando empacotada em `.exe`

## Estrutura do repositório

```text
.
├─ .github/workflows/python-check.yml
├─ build_exe.bat
├─ GITHUB_PREP.md
├─ HzApp.spec
├─ hz_power_switcher.ico
├─ hz_power_switcher.py
├─ PUBLISH_TO_GITHUB.ps1
├─ README.md
└─ requirements.txt
```

## Publicar no GitHub

### Opção rápida com GitHub CLI
```powershell
.\PUBLISH_TO_GITHUB.ps1 -RepoName "hz-power-switcher" -Visibility private
```

### Opção manual
```powershell
git init
git branch -M main
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/SEU-UTILIZADOR/hz-power-switcher.git
git push -u origin main
```
