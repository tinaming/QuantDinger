# replace-brand.ps1 — Safe batch brand replacement for frontend static files
# Usage: .\replace-brand.ps1
$ErrorActionPreference = "Stop"
$root = Join-Path $PSScriptRoot "html"

# File extensions to process
$exts = @("*.html", "*.js", "*.css", "*.json", "*.svg")

# --- Protection list: patterns that must NOT be replaced ---
# These are domain URLs, API endpoints, download links, referral codes
$protected = @(
    @{ Pattern = "quantdinger.com";        Placeholder = "__PROT_QD_COM__" },
    @{ Pattern = "api.quantdinger";        Placeholder = "__PROT_API_QD__" },
    @{ Pattern = "www.quantdinger";        Placeholder = "__PROT_WWW_QD__" },
    @{ Pattern = "ref=QUANTDINGER";        Placeholder = "__PROT_REF_QD__" }
)

# Counters
$totalFiles = 0
$modifiedFiles = 0

Get-ChildItem -Path $root -Recurse -Include $exts | ForEach-Object {
    $totalFiles++
    $file = $_.FullName
    $content = Get-Content $file -Raw -Encoding UTF8
    $original = $content

    # Step 1: Protect sensitive patterns
    foreach ($p in $protected) {
        $content = $content.Replace($p.Pattern, $p.Placeholder)
    }

    # Step 2: Brand replacements (case-specific, order matters)
    $content = $content.Replace("QuantDinger", "ChanQuant")
    $content = $content.Replace("QUANTDINGER", "CHANQUANT")
    $content = $content.Replace("quantdinger", "chanquant")

    # Step 3: Restore protected patterns
    foreach ($p in $protected) {
        $content = $content.Replace($p.Placeholder, $p.Pattern)
    }

    # Step 4: Write only if changed
    if ($content -ne $original) {
        Set-Content $file -Value $content -Encoding UTF8 -NoNewline
        $modifiedFiles++
        Write-Host "  [MODIFIED] $($_.FullName | Split-Path -Leaf)" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "=== Brand Replacement Complete ===" -ForegroundColor Green
Write-Host "  Total files scanned : $totalFiles"
Write-Host "  Files modified      : $modifiedFiles"
Write-Host "  Replacements        : QuantDinger -> ChanQuant"
Write-Host "  Protected patterns  : $($protected.Count) (domain URLs, referral codes)"
Write-Host ""
