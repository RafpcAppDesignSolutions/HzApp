# Hz Power Switcher

[![CI](https://github.com/RafpcAppDesignSolutions/HzApp/actions/workflows/python-check.yml/badge.svg)](https://github.com/RafpcAppDesignSolutions/HzApp/actions/workflows/python-check.yml)
[![Release](https://img.shields.io/github/v/release/RafpcAppDesignSolutions/HzApp)](https://github.com/RafpcAppDesignSolutions/HzApp/releases)
[![License](https://img.shields.io/github/license/RafpcAppDesignSolutions/HzApp)](LICENSE)

App Windows para alternar a frequência do ecrã conforme o estado de alimentação.

## Sobre

Esta app nasceu da vontade de contornar um comportamento que eu tinha encontrado no `G-Helper` no meu `ASUS X360`, onde a troca automática de Hz não estava a funcionar como eu precisava. Em vez de procurar uma solução mais pesada, explorei o problema de forma direta e simples, criando uma ferramenta focada só nesta tarefa.

## Inspiração

- comportamento esperado no `G-Helper`
- necessidade real de trocar Hz consoante corrente/bateria
- curiosidade técnica sobre como o Windows expõe as frequências disponíveis

## Propósito

- dar uma alternativa leve e focada para gerir Hz
- automatizar a troca entre energia e bateria
- manter a solução simples, sem depender de componentes mais pesados
- usar apenas as frequências que o Windows expõe para o ecrã ativo

## Funcionalidades

- troca entre frequência para corrente e bateria
- usa apenas valores que o Windows expõe para o ecrã ativo
- arranque com o Windows
- arranque minimizada
- ícone na bandeja do sistema

## Instalação

```powershell
pip install -r requirements.txt
python hz_power_switcher.py
```

## Build

```powershell
pip install pyinstaller
build_exe.bat
```

O executável fica em `dist\HzPowerSwitcher.exe`.

## Download

- o `exe` é anexado aos releases do GitHub
- existe também um pacote `zip` portátil para distribuição rápida
- existe um installer Windows com atalhos e desinstalação

## Release

O repositório publica automaticamente o binário quando é criada uma tag `v*`.

## Installer

O instalador cria:

- entrada em `Program Files`
- atalhos no Menu Iniciar
- opção para atalho no Desktop
- desinstalador padrão do Windows

## Ficheiros principais

- `hz_power_switcher.py`
- `hz_power_switcher.ico`
- `requirements.txt`
- `build_exe.bat`
- `.github/workflows/python-check.yml`
- `.github/workflows/release.yml`
- `installer/HzApp.iss`

## Configuração local

- `%LOCALAPPDATA%\HzPowerSwitcher\config.json`
- `%LOCALAPPDATA%\HzPowerSwitcher\app.log`

## Licença

MIT. Ver [LICENSE](/c:/Users/ruica/OneDrive/App%20Hz/LICENSE).
