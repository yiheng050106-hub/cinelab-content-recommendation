param([ValidateSet('Start','Stop')][string]$Action = 'Start')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$courseRoot = Split-Path $PSScriptRoot -Parent
$runtime = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'local.runtime.json') -Raw | ConvertFrom-Json
$state = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'local.development.json') -Raw | ConvertFrom-Json
if ($runtime.schema -ne 'cinelab-runtime-v1' -or $state.schema -ne 'cinelab-development-v1' -or
    $runtime.project -cne $state.project -or $runtime.engineId -cne $state.engineId) {
    throw 'Saved course runtime and development images do not match.'
}
$info = (docker info --format '{{json .}}' | ConvertFrom-Json)
if ($LASTEXITCODE -ne 0 -or $info.ID -cne $runtime.engineId -or $info.OSType -ne 'linux') {
    throw 'Docker engine identity or platform changed.'
}
if ((docker context show).Trim() -cne $runtime.context) { throw 'Docker context changed.' }
$env:COURSE_WEB_PORT = [string]$runtime.port
$env:COURSE_SECRET_DIR = [string]$runtime.secretDir
$env:COMPOSE_PROFILES = ''
$secretPath = if ([IO.Path]::IsPathRooted($runtime.secretDir)) { $runtime.secretDir } else { Join-Path $courseRoot $runtime.secretDir }
foreach ($secret in @('mysql-root-password','app-password','jwt-secret')) {
    if (-not (Test-Path -LiteralPath (Join-Path $secretPath $secret) -PathType Leaf)) { throw "Course secret missing: $secret" }
}
$override = "services:`n"
foreach ($service in @('api','web')) {
    $entry = @($state.images | Where-Object { $_.service -ceq $service })
    if ($entry.Count -ne 1) { throw "Missing development image for $service" }
    $image = docker image inspect $entry[0].reference --format '{{json .}}' | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or $image.Id -cne $entry[0].id -or $image.Os -ne 'linux') {
        throw "Development image changed: $service"
    }
    $override += "  ${service}:`n    image: $($entry[0].reference)`n"
}
$overridePath = Join-Path $PSScriptRoot ('local.extensions.' + [guid]::NewGuid().ToString('N') + '.yaml')
try {
    [IO.File]::WriteAllText($overridePath, $override, [Text.UTF8Encoding]::new($false))
    $common = @('--project-directory', $courseRoot,
        '--env-file', (Join-Path $PSScriptRoot 'offline/runtime.env'),
        '--file', (Join-Path $courseRoot 'compose.yaml'),
        '--file', $overridePath, '--file', (Join-Path $PSScriptRoot 'extensions.compose.yaml'),
        '--project-name', $runtime.project)
    if ($Action -eq 'Start') {
        docker compose @common config --quiet
        if ($LASTEXITCODE -ne 0) { throw 'Extension compose configuration invalid.' }
        docker compose @common up -d --no-build --pull never --wait --wait-timeout 300 api web
        if ($LASTEXITCODE -ne 0) { throw 'Extension startup failed.' }
        Write-Output "Extensions running at http://127.0.0.1:$($runtime.port)/experiments"
    } else {
        docker compose @common stop kafka api web
        if ($LASTEXITCODE -ne 0) { throw 'Extension stop failed.' }
    }
} finally {
    if (Test-Path -LiteralPath $overridePath) { Remove-Item -LiteralPath $overridePath -Force }
}
