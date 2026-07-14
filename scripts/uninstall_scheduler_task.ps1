param(
    [string]$TaskName = "StockPlatformScheduler"
)

$ErrorActionPreference = "Stop"

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask `
        -TaskName $TaskName `
        -Confirm:$false

    Write-Host "삭제 완료: $TaskName"
}
else {
    Write-Host "등록된 작업이 없습니다: $TaskName"
}
