# Hz Power Switcher

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

## Ficheiros principais

- `hz_power_switcher.py`
- `hz_power_switcher.ico`
- `requirements.txt`
- `build_exe.bat`
- `.github/workflows/python-check.yml`

## Configuração local

- `%LOCALAPPDATA%\HzPowerSwitcher\config.json`
- `%LOCALAPPDATA%\HzPowerSwitcher\app.log`

## Licença

MIT. Ver [LICENSE](/c:/Users/ruica/OneDrive/App%20Hz/LICENSE).
