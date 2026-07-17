$ErrorActionPreference = "Stop"

$Python = "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    Write-Host "Bundled Codex Python was not found. Falling back to python on PATH."
    $Python = "python"
}

& $Python -m streamlit run dashboard\streamlit_app.py --server.headless true --server.port 8501
