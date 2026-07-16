$body = '{"question":"给我看看抖音现在有什么热点"}'
try {
    $r = Invoke-WebRequest -Uri "http://localhost:8000/api/hot/ask" -Method POST -ContentType "application/json; charset=utf-8" -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 120 -UseBasicParsing
    Write-Host "STATUS: $($r.StatusCode)"
    Write-Host $r.Content
} catch {
    Write-Host "ERROR: $($_.Exception.Message)"
    $streamReader = [System.IO.StreamReader]::new($_.Exception.Response.GetResponseStream())
    $errBody = $streamReader.ReadToEnd()
    Write-Host $errBody
}
