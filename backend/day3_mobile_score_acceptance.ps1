# D-track Day 3 manual acceptance: replay the exact payloads the mobile score page sends
# against a REAL backend, and assert the Day 3 exit criteria.
#
#   A  only big score         -> accepted, FINISHED, games empty (no fabricated per-game scores)
#   B  big score + full games -> accepted, games stored correctly
#   C  invalid per-game data  -> rejected 422 with readable business message
#   D  abnormal result        -> accepted, result_type/forfeit_entry_id stored, no per-game scores
#   E  duplicate submit       -> same request_id is idempotent (no double write)
#   F  already finished       -> rejected 409
#
# NOTE: this file is ASCII-only on purpose. Windows PowerShell 5.1 reads a BOM-less .ps1
# as ANSI, which corrupts non-ASCII content (the trap documented in docs/WORKSTREAM_D.md 17.4).
#
# Usage:
#   1. cd backend
#   2. $env:DEMO_DB_PATH='data\d3_acceptance.db'
#   3. .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8099
#   4. (another shell) powershell -File .\day3_mobile_score_acceptance.ps1
#
# Companion scripts and prerequisites: see the header of scripts_mobile_viewport_check.mjs
# (the Day 3 acceptance quartet: this file, the two fixtures, the CDP scripts).

$ErrorActionPreference = 'Stop'
$base = 'http://127.0.0.1:8099'
$script:results = [System.Collections.Generic.List[string]]::new()

function Step($name, $ok, $detail) {
  $tag = if ($ok) { 'PASS' } else { 'FAIL' }
  $script:results.Add("[$tag] $name :: $detail")
  Write-Host "[$tag] $name :: $detail"
}

function Try-ParseJson($text) {
  if (-not $text) { return $null }
  try { return ($text | ConvertFrom-Json) } catch { return $null }
}

function Send-Json($method, $url, $body) {
  $contentType = $null
  $rawBody = $null
  if ($null -ne $body) {
    $contentType = 'application/json'
    $rawBody = ($body | ConvertTo-Json -Depth 8 -Compress)
  }
  try {
    # -UseBasicParsing: no IE engine, and no interactive confirmation prompt
    $resp = Invoke-WebRequest -Uri $url -Method $method -TimeoutSec 15 -UseBasicParsing `
      -ErrorAction Stop -ContentType $contentType -Body $rawBody
    return @{ status = [int]$resp.StatusCode; body = (Try-ParseJson $resp.Content); raw = $resp.Content }
  } catch {
    $status = 0
    if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
    $text = $_.ErrorDetails.Message
    if (-not $text) { $text = $_.Exception.Message }
    return @{ status = $status; body = (Try-ParseJson $text); raw = $text }
  }
}

function Detail-Of($response) {
  if ($response.body -and $response.body.detail) { return [string]$response.body.detail }
  return [string]$response.raw
}

function Get-MatchById($tournamentId, $matchId) {
  $all = Invoke-RestMethod -Uri "$base/api/tournaments/$tournamentId/matches" -TimeoutSec 15
  return ($all | Where-Object { $_.id -eq $matchId })
}

Write-Host '=== setup ==='

$created = Send-Json 'POST' "$base/api/tournaments" @{
  name = 'D3 acceptance (disposable)'
  date = '2026-01-01'
  table_count = 4
  group_count = 2
  qualify_per_group = 2
  event_type = 'SINGLES'
  operation_mode = 'LIVE'
  games_to_win = 2
  points_to_win = 11
}
if ($created.status -lt 200 -or $created.status -ge 300 -or -not $created.body.id) {
  Write-Host "SETUP FAILED: HTTP $($created.status) $($created.raw)"
  exit 1
}
$tid = $created.body.id
Write-Host "tournament id=$tid  games_to_win=$($created.body.games_to_win)  points_to_win=$($created.body.points_to_win)"

foreach ($playerName in @('P1', 'P2', 'P3', 'P4', 'P5', 'P6')) {
  Send-Json 'POST' "$base/api/tournaments/$tid/players" @{ name = $playerName } | Out-Null
}
Send-Json 'POST' "$base/api/tournaments/$tid/auto-group" @{} | Out-Null
$generated = Send-Json 'POST' "$base/api/tournaments/$tid/generate-group-matches" @{}
Write-Host "group matches generated: $($generated.body.matches_generated)"

$matches = Invoke-RestMethod -Uri "$base/api/tournaments/$tid/matches" -TimeoutSec 15
Write-Host "GET /api/tournaments/$tid/matches returned $($matches.Count) matches (this is how MobileScorePage locates one match)"
Step 'route data source: match list by tournament id' ($matches.Count -ge 5) "count=$($matches.Count)"
$foreign = @($matches | Where-Object { $_.tournament_id -ne $tid })
Step 'every returned match belongs to this tournament' ($foreign.Count -eq 0) "foreign=$($foreign.Count)"

# ---------------------------------------------------------------- A
Write-Host ''
Write-Host '=== A: big score only (no per-game scores) ==='
$mA = $matches[0]
$payloadA = @{
  player_a_score = 2
  player_b_score = 1
  result_type = 'NORMAL'
  request_id = [guid]::NewGuid().ToString()
}
$resA = Send-Json 'POST' "$base/api/matches/$($mA.id)/score" $payloadA
Step 'A accepted' ($resA.status -eq 200) "HTTP $($resA.status)"

$afterA = Get-MatchById $tid $mA.id
Step 'A match FINISHED' ($afterA.status -eq 'FINISHED') "status=$($afterA.status)"
Step 'A big score stored' ($afterA.player_a_score -eq 2 -and $afterA.player_b_score -eq 1) "$($afterA.player_a_score):$($afterA.player_b_score)"
Step 'A no fabricated per-game scores' ($afterA.games.Count -eq 0) "games=$($afterA.games.Count)"

# ---------------------------------------------------------------- E
Write-Host ''
Write-Host '=== E: duplicate submit with same request_id (phone double tap / network retry) ==='
$resE = Send-Json 'POST' "$base/api/matches/$($mA.id)/score" $payloadA
Step 'E same request_id returns 200 (idempotent replay)' ($resE.status -eq 200) "HTTP $($resE.status)"
$auditsA = Invoke-RestMethod -Uri "$base/api/matches/$($mA.id)/score-audits" -TimeoutSec 15
$recordCount = @($auditsA | Where-Object { $_.action -eq 'RECORD' }).Count
Step 'E only one RECORD audit row (no double write)' ($recordCount -eq 1) "RECORD rows=$recordCount"

$payloadE2 = @{
  player_a_score = 2
  player_b_score = 0
  result_type = 'NORMAL'
  request_id = $payloadA.request_id
}
$resE2 = Send-Json 'POST' "$base/api/matches/$($mA.id)/score" $payloadE2
Step 'E same request_id with different payload rejected (409)' ($resE2.status -eq 409) "HTTP $($resE2.status) detail=$(Detail-Of $resE2)"

# ---------------------------------------------------------------- B
Write-Host ''
Write-Host '=== B: big score + complete per-game scores in one submit ==='
$mB = $matches[1]
$payloadB = @{
  player_a_score = 2
  player_b_score = 1
  games = @(
    @{ side_a_score = 11; side_b_score = 7 },
    @{ side_a_score = 9; side_b_score = 11 },
    @{ side_a_score = 11; side_b_score = 8 }
  )
  result_type = 'NORMAL'
  request_id = [guid]::NewGuid().ToString()
}
$resB = Send-Json 'POST' "$base/api/matches/$($mB.id)/score" $payloadB
Step 'B accepted' ($resB.status -eq 200) "HTTP $($resB.status)"
$afterB = Get-MatchById $tid $mB.id
$gamesText = (($afterB.games | Sort-Object game_no | ForEach-Object { "$($_.side_a_score)-$($_.side_b_score)" }) -join ' / ')
Step 'B per-game scores stored correctly' ($gamesText -eq '11-7 / 9-11 / 11-8') "games=$gamesText"

# ---------------------------------------------------------------- C
Write-Host ''
Write-Host '=== C: invalid per-game scores (aggregate says A wins, games say B wins) ==='
$mC = $matches[2]
$payloadC = @{
  player_a_score = 2
  player_b_score = 1
  games = @(
    @{ side_a_score = 7; side_b_score = 11 },
    @{ side_a_score = 9; side_b_score = 11 }
  )
  result_type = 'NORMAL'
  request_id = [guid]::NewGuid().ToString()
}
$resC = Send-Json 'POST' "$base/api/matches/$($mC.id)/score" $payloadC
Step 'C rejected by server' ($resC.status -eq 422) "HTTP $($resC.status) detail=$(Detail-Of $resC)"
$afterC = Get-MatchById $tid $mC.id
Step 'C match untouched after rejection' ($afterC.status -ne 'FINISHED' -and $afterC.games.Count -eq 0) "status=$($afterC.status) games=$($afterC.games.Count)"

$resC2 = Send-Json 'POST' "$base/api/matches/$($mC.id)/score" @{
  player_a_score = 2; player_b_score = 2; result_type = 'NORMAL'; request_id = [guid]::NewGuid().ToString()
}
Step 'C draw rejected 422' ($resC2.status -eq 422) "HTTP $($resC2.status) detail=$(Detail-Of $resC2)"

$resC3 = Send-Json 'POST' "$base/api/matches/$($mC.id)/score" @{
  player_a_score = 2; player_b_score = 1
  games = @(@{ side_a_score = 11; side_b_score = 0 }, @{ side_a_score = 11; side_b_score = 0 })
  result_type = 'NORMAL'; request_id = [guid]::NewGuid().ToString()
}
Step 'C inconsistent games rejected 422' ($resC3.status -eq 422) "HTTP $($resC3.status) detail=$(Detail-Of $resC3)"

# ---------------------------------------------------------------- D
Write-Host ''
Write-Host '=== D: abnormal result (side B forfeits) ==='
$mD = $matches[3]
$forfeitEntryId = if ($mD.entry_b_id) { $mD.entry_b_id } else { $mD.player_b_id }
$payloadD = @{
  result_type = 'FORFEIT'
  forfeit_entry_id = $forfeitEntryId
  note = 'manual acceptance: forfeit'
  request_id = [guid]::NewGuid().ToString()
}
$resD = Send-Json 'POST' "$base/api/matches/$($mD.id)/score" $payloadD
Step 'D accepted' ($resD.status -eq 200) "HTTP $($resD.status)"
$afterD = Get-MatchById $tid $mD.id
Step 'D result_type=FORFEIT' ($afterD.result_type -eq 'FORFEIT') "result_type=$($afterD.result_type)"
Step 'D forfeit_entry_id stored (side B)' ($afterD.forfeit_entry_id -eq $forfeitEntryId) "forfeit_entry_id=$($afterD.forfeit_entry_id)"
Step 'D no per-game scores created' ($afterD.games.Count -eq 0) "games=$($afterD.games.Count)"
Step 'D admin score for ranking is labelled, not a real score' ($afterD.player_a_score -eq 2 -and $afterD.player_b_score -eq 0) "admin score=$($afterD.player_a_score):$($afterD.player_b_score) (page shows it as ranking-only)"

$resD2 = Send-Json 'POST' "$base/api/matches/$($matches[4].id)/score" @{
  result_type = 'FORFEIT'; forfeit_entry_id = 999999; request_id = [guid]::NewGuid().ToString()
}
Step 'D bad forfeit side rejected 422' ($resD2.status -eq 422) "HTTP $($resD2.status) detail=$(Detail-Of $resD2)"

# ---------------------------------------------------------------- F
Write-Host ''
Write-Host '=== F: submitting again on a finished match ==='
$resF = Send-Json 'POST' "$base/api/matches/$($mA.id)/score" @{
  player_a_score = 2; player_b_score = 0; result_type = 'NORMAL'; request_id = [guid]::NewGuid().ToString()
}
Step 'F rejected 409' ($resF.status -eq 409) "HTTP $($resF.status) detail=$(Detail-Of $resF)"

Write-Host ''
Write-Host '=== summary ==='
$pass = @($script:results | Where-Object { $_ -like '`[PASS`]*' }).Count
$fail = @($script:results | Where-Object { $_ -like '`[FAIL`]*' }).Count
Write-Host "PASS=$pass FAIL=$fail"
if ($fail -gt 0) { exit 1 }
