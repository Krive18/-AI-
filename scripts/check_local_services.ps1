param(
    [string]$MySqlHostName = '127.0.0.1',
    [int]$MySqlPort = 3306,
    [string]$RedisHostName = '127.0.0.1',
    [int]$RedisPort = 6379,
    [int]$TimeoutMilliseconds = 1500
)

$ErrorActionPreference = 'Stop'

function Assert-TcpEndpoint {
    param([string]$Name, [string]$HostName, [int]$Port)
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $connected = $client.ConnectAsync($HostName, $Port).Wait($TimeoutMilliseconds)
        if (-not $connected -or -not $client.Connected) {
            throw "$Name is unavailable at ${HostName}:${Port}"
        }
    }
    finally {
        $client.Dispose()
    }
}

Assert-TcpEndpoint -Name 'MySQL' -HostName $MySqlHostName -Port $MySqlPort
Assert-TcpEndpoint -Name 'Redis' -HostName $RedisHostName -Port $RedisPort
