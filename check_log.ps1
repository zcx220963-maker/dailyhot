Get-Content "C:\Users\xu'zhi'cheng\Desktop\agent\search-agent\gpt-researcher\uvicorn.log" -Tail 30 -ErrorAction SilentlyContinue
Write-Host "---ERR---"
Get-Content "C:\Users\xu'zhi'cheng\Desktop\agent\search-agent\gpt-researcher\uvicorn_err.log" -Tail 30 -ErrorAction SilentlyContinue
