$ErrorActionPreference = "Stop"
$Repository = "git+https://github.com/WolCarlos/Wol-rust-docs-pp-cli.git"

if (Get-Command uv -ErrorAction SilentlyContinue) {
    uv tool install --force $Repository
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    py -3 -m pip install --user $Repository
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    python -m pip install --user $Repository
} else {
    throw "Python 3.11+ or uv is required."
}

rust-docs-pp-cli sync
Write-Host "`nInstalled. Try: rust-docs-pp-cli which `"borrow checker`" --json"
