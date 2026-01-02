# Timeline CRM - Quick Reference

## Authentication & Base Setup

**Base URL:** `https://crm.actionapi.ca`
**API Key:** Stored in `$env:ACTO` environment variable
**Attribution:** All notes automatically tagged as "Michael ({{AGENT_NAME}})"

## PowerShell Pattern (Always Use This)

```powershell
powershell -Command 'Invoke-RestMethod -Uri "URL" -Headers @{"X-API-Key"=$env:ACTO} -Method Get'
```

## People Operations

### Search for Someone
```powershell
powershell -Command '$result = Invoke-RestMethod -Uri "https://crm.actionapi.ca/api/people/allslim" -Headers @{"X-API-Key"=$env:ACTO} -Method Get; $result | ConvertTo-Json -Depth 10 -Compress'
```

### Add Note to Person
```powershell
$email = "mike.smith@example.com"
$encoded = [System.Web.HttpUtility]::UrlEncode($email)
$note = "Note text here"
powershell -Command "$body = @{note='$note'} | ConvertTo-Json; Invoke-RestMethod -Uri 'https://crm.actionapi.ca/api/people/$encoded/notes' -Headers @{'X-API-Key'=$env:ACTO} -Method Post -ContentType 'application/json' -Body $body"
```

## Key Conventions
- **ACTION: prefix** - Flag notes requiring follow-up
- **Email encoding** - @ becomes %40 in URLs
