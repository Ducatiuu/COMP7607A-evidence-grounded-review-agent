# Configure a DeepSeek key without placing it in shell history or the repository.
# The key is saved for this Windows user only after a read-only authentication check.
$ErrorActionPreference = 'Stop'

$secureKey = Read-Host -Prompt 'Enter a new DeepSeek API key' -AsSecureString
$plainKey = $null
try {
    $plainKey = [System.Net.NetworkCredential]::new('', $secureKey).Password
    if ([string]::IsNullOrWhiteSpace($plainKey) -or $plainKey.Contains("`r") -or $plainKey.Contains("`n")) {
        throw 'The API key is empty or malformed.'
    }

    try {
        $models = Invoke-RestMethod -Method Get -Uri 'https://api.deepseek.com/models' `
            -Headers @{ Authorization = "Bearer $plainKey" } -TimeoutSec 20
    }
    catch {
        if ($_.Exception.Response) {
            $statusCode = [int]$_.Exception.Response.StatusCode
            throw "DeepSeek authentication check failed (HTTP $statusCode). No key was saved."
        }
        throw 'DeepSeek authentication check failed (network error). No key was saved.'
    }

    if ('deepseek-flash' -notin @($models.data | ForEach-Object { $_.id })) {
        throw 'The account did not list deepseek-flash. No key was saved.'
    }

    [Environment]::SetEnvironmentVariable('DEEPSEEK_API_KEY', $plainKey, 'User')
    Write-Output 'DeepSeek key verified and saved for this Windows user. Restart Codex before live runs.'
}
finally {
    Remove-Variable plainKey, secureKey -ErrorAction SilentlyContinue
}
