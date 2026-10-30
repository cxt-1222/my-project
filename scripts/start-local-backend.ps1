$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

function Invoke-DockerCompose {
    param([Parameter(Mandatory)][string[]]$Arguments)

    $output = & docker compose @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    $output | ForEach-Object { Write-Host $_ }
    if ($exitCode -ne 0) {
        throw "docker compose $($Arguments -join ' ') 失败（退出代码 $exitCode）。"
    }
}

if (-not (Test-Path '.venv\Scripts\python.exe')) {
    throw "未找到 Python 虚拟环境：$projectRoot\.venv。请先执行：python -m venv .venv"
}

Write-Host '停止 Docker 中的 FastAPI 容器，释放本机 8000 端口...' -ForegroundColor Cyan
Invoke-DockerCompose -Arguments @('stop', 'aiagent-end')

Write-Host '启动后端依赖容器（不启动 aiagent-end 应用镜像）...' -ForegroundColor Cyan
Invoke-DockerCompose -Arguments @(
  'up', '-d', '--no-build',
  'postgres',
  'mongodb',
  'rabbitmq',
  'neo4j',
  'rustfs',
  'elasticsearch',
  'etcd',
  'minio',
  'milvus'
)

# 本机运行 FastAPI 时，不能使用 Docker 内部服务名，需要使用宿主机映射端口。
$env:POSTGRES_HOST = '127.0.0.1'
$env:POSTGRES_PORT = '5433'
$env:POSTGRES_USER = 'user'
$env:POSTGRES_PASSWORD = 'lyp82nlfxxlE'
$env:POSTGRES_DB = 'aiagent'

$env:MONGO_URI = 'mongodb://root:lyp82nlfxxlE@127.0.0.1:27018/?authSource=admin'
$env:DB_NAME = 'aiagent'

$env:RABBITMQ_URL = 'amqp://user:lyp82nlfxxlE@127.0.0.1:5672/aiagent'
$env:ES_HOST = 'http://127.0.0.1:9200'
$env:MILVUS_URL = 'http://127.0.0.1:19530'
$env:NEO4J_URI = 'bolt://127.0.0.1:7687'
$env:NEO4J_USER = 'neo4j'
$env:NEO4J_PASSWORD = 'password'
$env:RUSTFS_ENDPOINT = 'http://127.0.0.1:9010'

Write-Host '等待基础服务启动...' -ForegroundColor Cyan
Start-Sleep -Seconds 5

Write-Host '启动本机 FastAPI（代码修改会自动 reload）...' -ForegroundColor Green
& '.venv\Scripts\python.exe' -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
