<#
Deploys this FastAPI app to Azure App Service (Linux).

Usage examples:
.
# Create resources and deploy (requires logged-in az):
./scripts/deploy.ps1 -AppName oxblue-app

# Deploy existing code to an existing app and import .env settings:
./scripts/deploy.ps1 -AppName oxblue-app -EnvFile .env

Parameters:
-AppName (required): globally-unique App Service name.
-SubscriptionId: defaults to provided subscription.
-ResourceGroup: defaults to rg-oxblue
-Location: defaults to eastus2
-PlanName: defaults to oxblue-plan
-Sku: App Service Plan SKU (B1 recommended for small workloads)
-Runtime: Azure runtime string (e.g. "PYTHON|3.11")
-EnvFile: optional path to a .env file whose KEY=VALUE pairs will be added as App Settings.
-CreateInfrastructure: if passed, script will create resource group/plan if needed.
#>

param(
    [Parameter(Mandatory=$true)] [string]$AppName,
    [string]$SubscriptionId = '39d91308-5bee-4183-9f46-d92d4caf9898',
    [string]$ResourceGroup = 'rg-oxblue',
    [string]$Location = 'eastus2',
    [string]$PlanName = 'oxblue-plan',
    [string]$Sku = 'B1',
    [string]$Runtime = 'PYTHON|3.11',
    [string]$EnvFile = '.env',
    [switch]$CreateInfrastructure,
    [switch]$SkipCreate
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
# Prevent non-zero native command exits from auto-terminating before we can handle them.
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}

function Ensure-AzCliLoggedIn {
    try {
        az account show > $null 2>&1
    } catch {
        Write-Host "You must be logged in to Azure CLI. Running 'az login'..."
        az login | Out-Null
    }
}

function Parse-EnvFile {
    param([string]$Path)
    $pairs = @()
    if (-not (Test-Path $Path)) { return $pairs }
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if ($line -eq '' -or $line.StartsWith('#')) { return }
        if ($line -match "^([^=]+)=(.*)$") {
            $k = $matches[1].Trim()
            $v = $matches[2].Trim()
            $pairs += "$k=$v"
        }
    }
    return $pairs
}

Write-Host "Using subscription: $SubscriptionId"
az account set --subscription $SubscriptionId

Ensure-AzCliLoggedIn

$shouldCreateInfra = $CreateInfrastructure -and (-not $SkipCreate)

if ($shouldCreateInfra) {
    Write-Host "Creating resource group '$ResourceGroup' in '$Location' (if missing)..."
    az group create --name $ResourceGroup --location $Location | Out-Null

    Write-Host "Creating App Service plan '$PlanName' (Linux, SKU $Sku) (if missing)..."
    az appservice plan create --name $PlanName --resource-group $ResourceGroup --sku $Sku --is-linux --location $Location | Out-Null
} else {
    Write-Host "Skipping resource group/plan creation (existing infrastructure mode)."
}

# Ensure the web app exists; create it if missing. Quote runtime to avoid PowerShell pipe parsing.
$webappExists = $false
try {
    $tmp = az webapp show --name $AppName --resource-group $ResourceGroup --query "name" -o tsv 2>$null
    if ($tmp) { $webappExists = $true }
} catch {
    $webappExists = $false
}

if (-not $webappExists) {
    Write-Host "Creating web app '$AppName' (if missing)..."
    # Runtime with pipe (e.g. PYTHON|3.11) can be mangled by az.cmd on Windows shells.
    # Create the app first, then rely on startup command + build detection for deployment.
    $createArgs = @(
        'webapp', 'create',
        '--resource-group', $ResourceGroup,
        '--plan', $PlanName,
        '--name', $AppName
    )
    & az @createArgs | Out-Null
} else {
    Write-Host "Web app '$AppName' already exists in resource group '$ResourceGroup'."
}

$verifyName = az webapp show --name $AppName --resource-group $ResourceGroup --query "name" -o tsv 2>$null
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($verifyName)) {
    throw "Web app '$AppName' was not found or could not be created in resource group '$ResourceGroup'."
}

# Set startup command to use gunicorn + uvicorn worker for FastAPI
$startupCmd = 'gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app'
Write-Host "Setting startup command: $startupCmd"
$startupArgs = @(
    'webapp', 'config', 'set',
    '--resource-group', $ResourceGroup,
    '--name', $AppName,
    '--startup-file', $startupCmd
)
& az @startupArgs | Out-Null

# Ensure the app listens on port 8000
Write-Host "Setting WEBSITES_PORT=8000"
$portArgs = @(
    'webapp', 'config', 'appsettings', 'set',
    '--resource-group', $ResourceGroup,
    '--name', $AppName,
    '--settings', 'WEBSITES_PORT=8000'
)
& az @portArgs | Out-Null

# Parse .env and set app settings (optional)
$envPairs = Parse-EnvFile -Path $EnvFile
if ($envPairs.Count -gt 0) {
    Write-Host "Setting app settings from $EnvFile (skipping blank/comment lines)"
    $settingsArgs = @(
        'webapp', 'config', 'appsettings', 'set',
        '--resource-group', $ResourceGroup,
        '--name', $AppName,
        '--settings'
    ) + $envPairs
    & az @settingsArgs | Out-Null
}

# Create zip package of the app
$tempZip = Join-Path $env:TEMP ("$AppName-deploy.zip")
if (Test-Path $tempZip) { Remove-Item $tempZip -Force }
Write-Host "Creating zip package at $tempZip"

# Always package from project root (script can be run from anywhere)
$ProjectRoot = Split-Path -Parent $PSScriptRoot

Push-Location $ProjectRoot
try {
    # Compress project root contents. Keep .env out of package.
    $pathsToZip = @(
        'main.py',
        'config.py',
        'database.py',
        'models.py',
        'customers.py',
        'invoices.py',
        'payments.py',
        'agent.py',
        'requirements.txt',
        'aipaymentprocessor'
    )

    $existingPaths = $pathsToZip | Where-Object { Test-Path $_ }
    if ($existingPaths.Count -eq 0) {
        throw "No deployable files found in project root: $ProjectRoot"
    }

    Compress-Archive -Path $existingPaths -DestinationPath $tempZip -Force
}
finally {
    Pop-Location
}

Write-Host "Deploying zip to App Service ($AppName)"
$zipArgs = @(
    'webapp', 'deployment', 'source', 'config-zip',
    '--resource-group', $ResourceGroup,
    '--name', $AppName,
    '--src', $tempZip
)
& az @zipArgs | Out-Null

$websiteUrl = "https://$AppName.azurewebsites.net"
Write-Host "Deployment complete. App URL: $websiteUrl"
Write-Host "Tip: view logs with 'az webapp log tail -g $ResourceGroup -n $AppName'"
