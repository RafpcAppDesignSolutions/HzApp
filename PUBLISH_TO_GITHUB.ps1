param(
    [Parameter(Mandatory = $true)]
    [string]$RepoName,

    [ValidateSet("private", "public")]
    [string]$Visibility = "private"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "GitHub CLI ('gh') não está instalado ou não está no PATH."
}

if (-not (Test-Path ".git")) {
    git init | Out-Null
    git branch -M main | Out-Null
}

if (-not (git remote get-url origin 2>$null)) {
    $owner = gh api user --jq .login
    $repoUrl = "https://github.com/$owner/$RepoName.git"
    git remote add origin $repoUrl | Out-Null
}

git add . | Out-Null
git commit -m "Initial commit" 2>$null | Out-Null

gh repo create $RepoName --$Visibility --source . --remote origin --push
