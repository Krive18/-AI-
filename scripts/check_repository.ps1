$ErrorActionPreference = 'Stop'
py -3.13 -c "import tomllib, pathlib; tomllib.loads(pathlib.Path('backend/pyproject.toml').read_text('utf-8'))"
if ($LASTEXITCODE -ne 0) { throw "Python manifest check failed with exit code $LASTEXITCODE" }
py -3.13 -m uv lock --project backend --check
if ($LASTEXITCODE -ne 0) { throw "Python lock check failed with exit code $LASTEXITCODE" }
node -e "const p=require('./frontend/package.json'); if(!p.scripts?.build) process.exit(1)"
if ($LASTEXITCODE -ne 0) { throw "Node manifest check failed with exit code $LASTEXITCODE" }
