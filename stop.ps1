Get-Process | Where-Object { $_.ProcessName -in @("python", "node") } |
  Where-Object { $_.Path -like "*MediAgent*" } |
  ForEach-Object { Write-Host "停止 $($_.ProcessName) (PID $($_.Id))" -ForegroundColor Yellow; Stop-Process -Id $_.Id -Force }
Write-Host "已尝试停止 MediAgent 相关进程。" -ForegroundColor Green
