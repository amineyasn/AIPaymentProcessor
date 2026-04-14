# Parameters
$subscriptionId = "39d91308-5bee-4183-9f46-d92d4caf9898"
$resourceGroup = "rg-oxblue"
$planName = "oxblue-plan"
$appName = "aipaymentprocessor-app" # Ensure this is unique
$location = "East US 2"

# 1. Move to the project root (one level up from \scripts\)
Set-Location "$PSScriptRoot\.."
Write-Host "Working in: $(Get-Location)" -ForegroundColor Gray

# 2. Login & Set Subscription
az account set --subscription $subscriptionId

# 3. Create/Update App Service
Write-Host "Ensuring App Service exists with Python 3.11..." -ForegroundColor Cyan
az webapp create --name $appName --resource-group $resourceGroup --plan $planName --runtime "PYTHON:3.11"

# 4. Configure FastAPI & Build Settings
az webapp config appsettings set --name $appName --resource-group $resourceGroup --settings `
    SCM_DO_BUILD_DURING_DEPLOYMENT=true `
    PYTHON_VERSION=3.11

az webapp config set --name $appName --resource-group $resourceGroup --startup-file "gunicorn -w 4 -k uvicorn.workers.UvicornWorker --bind=0.0.0.0:8000 main:app"

# 5. Sync .env to Azure
if (Test-Path ".env") {
    Write-Host "Syncing .env variables..." -ForegroundColor Cyan
    Get-Content .env | Where-Object { $_ -match "=" -and $_ -notmatch "^#" } | ForEach-Object {
        az webapp config appsettings set --name $appName --resource-group $resourceGroup --settings $_
    }
}

# 6. Create Deployment Zip (The Fixed Way)
$zipFile = "deploy.zip"
if (Test-Path $zipFile) { Remove-Item $zipFile }

Write-Host "Creating deployment package..." -ForegroundColor Cyan
# Using Get-ChildItem to filter, then piping to Compress-Archive
Get-ChildItem -Path .* , * -Exclude ".git", ".venv", "__pycache__", "scripts", $zipFile | 
    Compress-Archive -DestinationPath $zipFile

# 7. Deploy using the new 'az webapp deploy' command
Write-Host "Pushing code to Azure..." -ForegroundColor Cyan
az webapp deploy --name $appName --resource-group $resourceGroup --src-path $zipFile --type zip

# Cleanup
Remove-Item $zipFile
Write-Host "Deployment Complete! https://$appName.azurewebsites.net" -ForegroundColor Green