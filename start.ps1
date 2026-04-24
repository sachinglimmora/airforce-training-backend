$ErrorActionPreference = "Stop"

if (Test-Path ".\.venv\Scripts\Activate.ps1") {
    . ".\.venv\Scripts\Activate.ps1"
} else {
    Write-Host "Virtual environment not found at .venv" -ForegroundColor Red
    exit 1
}

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
