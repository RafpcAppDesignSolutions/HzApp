# Hz Power Switcher

App Windows para alternar a frequência do ecrã conforme o estado de alimentação.

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
