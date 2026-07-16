$env:PYTHONPATH = "C:\Users\xu'zhi'cheng\Desktop\agent\search-agent\gpt-researcher"
Set-Location "C:\Users\xu'zhi'cheng\Desktop\agent\search-agent\gpt-researcher\backend"

# 清理旧的 uvicorn 进程（端口冲突保护）
Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -like '*uvicorn*server.app*'
} | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

# 清理旧的 .pyc 缓存（确保使用最新代码）
Get-ChildItem -Path "C:\Users\xu'zhi'cheng\Desktop\agent\search-agent\gpt-researcher\gpt_researcher" -Recurse -Filter "*.pyc" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path "C:\Users\xu'zhi'cheng\Desktop\agent\search-agent\gpt-researcher\gpt_researcher" -Recurse -Filter "__pycache__" -Directory -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Start-Process -FilePath "python" -ArgumentList @("-m","uvicorn","server.app:app","--host","0.0.0.0","--port","8000") -WindowStyle Hidden -RedirectStandardOutput "C:\Users\xu'zhi'cheng\Desktop\agent\search-agent\gpt-researcher\uvicorn.log" -RedirectStandardError "C:\Users\xu'zhi'cheng\Desktop\agent\search-agent\gpt-researcher\uvicorn_err.log"
Start-Sleep -Seconds 5
Get-Content "C:\Users\xu'zhi'cheng\Desktop\agent\search-agent\gpt-researcher\uvicorn.log" -Tail 20
