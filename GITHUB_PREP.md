# GitHub prep

## O que foi limpo
- removido `.venv`
- removida pasta `build`
- removido `__pycache__`
- removidos logs locais e ficheiros de output

## O que ficou
- código fonte
- ícone
- README
- requirements
- ficheiro `.spec`
- batch de build
- `.gitignore`
- workflow básico GitHub Actions

## Publicação recomendada
### Método 1 — GitHub CLI
```powershell
.\PUBLISH_TO_GITHUB.ps1 -RepoName "hz-power-switcher" -Visibility private
```

### Método 2 — Git manual
```powershell
git init
git branch -M main
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/SEU-UTILIZADOR/hz-power-switcher.git
git push -u origin main
```

## Nota
Cria o repositório no GitHub sem README / license / gitignore automáticos, porque estes ficheiros já estão preparados localmente.
