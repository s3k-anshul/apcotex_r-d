$response = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/auth/login" -Method Post -Body '{"username": "admin", "password": "Admin@123!"}' -ContentType "application/json"
$token = $response.data.access_token

$out = "Token: $token`n"

try {
    $resp = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/admin/usage/by-stage" -Headers @{Authorization = "Bearer $token"}
    $out += "by-stage Success`n"
} catch {
    $out += "by-stage Error: $($_.Exception.Message)`n"
    $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
    $reader.BaseStream.Position = 0
    $reader.DiscardBufferedData()
    $out += "by-stage Body: $($reader.ReadToEnd())`n"
}

$out | Out-File -FilePath "scratch\out.txt"
