# Build student extensions on the imported offline course images.
# This file is separate from the release-checked course build.ps1.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$courseRoot = Split-Path $PSScriptRoot -Parent
$runtime = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'local.runtime.json') -Raw | ConvertFrom-Json
if ($runtime.schema -ne 'cinelab-runtime-v1') { throw 'Course runtime has not been initialized.' }
$engine = docker info --format '{{.ID}}'
if ($LASTEXITCODE -ne 0 -or $engine.Trim() -cne $runtime.engineId) { throw 'Docker engine identity changed.' }
$context = Join-Path $courseRoot ('.extension-build-' + [guid]::NewGuid().ToString('N'))
if ($context -match '[^\x00-\x7F]') { throw 'Move the source to an ASCII-only path for Docker BuildKit.' }
New-Item -ItemType Directory -Path $context | Out-Null
try {
    Push-Location $courseRoot
    try { python -m recommender.student.build_rrf; if ($LASTEXITCODE -ne 0) { throw 'RRF manifest generation failed.' } }
    finally { Pop-Location }
    Push-Location (Join-Path $courseRoot 'frontend')
    try {
        if (-not (Test-Path -LiteralPath 'node_modules')) { npm ci --no-audit --no-fund; if ($LASTEXITCODE -ne 0) { throw 'npm install failed.' } }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    } finally { Pop-Location }

    $files = @()
    foreach ($part in @('backend','recommender')) {
        $files += @(Get-ChildItem -LiteralPath (Join-Path $courseRoot $part) -Recurse -File -Filter '*.py')
    }
    $files += @(Get-ChildItem -LiteralPath (Join-Path $courseRoot 'deployment/wheels') -File -Filter '*.whl')
    $files += @(Get-ChildItem -LiteralPath (Join-Path $courseRoot 'frontend/dist') -Recurse -File)
    foreach ($file in $files) {
        $relative = $file.FullName.Substring($courseRoot.Length + 1)
        $destination = Join-Path $context $relative
        New-Item -ItemType Directory -Force -Path (Split-Path $destination -Parent) | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $destination
    }
    [IO.File]::WriteAllText((Join-Path $context 'api.Dockerfile'), @'
FROM cinelab-offline/api:1.3.0-a1
USER root
COPY deployment/wheels/ /tmp/wheels/
RUN pip install --no-cache-dir --no-index --find-links=/tmp/wheels kafka-python==2.2.15
COPY backend/ /app/backend/
COPY recommender/ /app/recommender/
USER 10001
'@, [Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText((Join-Path $context 'web.Dockerfile'), @'
FROM cinelab-offline/web:1.3.0-a1
COPY frontend/dist/ /usr/share/nginx/html/
USER nginx
'@, [Text.UTF8Encoding]::new($false))
    $tag = [guid]::NewGuid().ToString('N')
    $images = @()
    foreach ($service in @('api','web')) {
        $reference = "cinelab-student/$($runtime.project)-${service}:$tag"
        docker build --platform linux/amd64 --file (Join-Path $context "$service.Dockerfile") --tag $reference $context
        if ($LASTEXITCODE -ne 0) { throw "Docker build failed: $service" }
        $image = docker image inspect $reference --format '{{json .}}' | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0 -or $image.Os -ne 'linux' -or $image.Architecture -ne 'amd64') {
            throw "Built image platform invalid: $service"
        }
        $images += [pscustomobject]@{service=$service;reference=$reference;id=$image.Id}
    }
    $state = [pscustomobject]@{schema='cinelab-development-v1';project=$runtime.project;
        engineId=$runtime.engineId;images=$images}
    $state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'local.development.json') -Encoding UTF8
    Write-Output 'Extension images built. Run deployment/start-extensions.ps1 -Action Start.'
} finally {
    $resolved = [IO.Path]::GetFullPath($context)
    $parent = [IO.Path]::GetFullPath($courseRoot).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
    if (-not $resolved.StartsWith($parent, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe build cleanup path.' }
    if (Test-Path -LiteralPath $resolved) { Remove-Item -LiteralPath $resolved -Recurse -Force }
}
