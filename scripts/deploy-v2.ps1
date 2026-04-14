# Parameters
$subscriptionId = "39d91308-5bee-4183-9f46-d92d4caf9898"
$resourceGroup = "rg-oxblue"
$planName = "oxblue-plan"
$appName = "aipaymentprocessor-app-fastapi"
$location = "East US 2"

# 1. Login & Set Subscription
az account set --subscription $subscriptionId

# 2. Create the App Service shell (Linux)
Write-Host "Initializing App Service..." -ForegroundColor Cyan
az webapp create --name $appName --resource-group $resourceGroup --plan $planName --runtime "PYTHON:3.11"

# 3. Configure FastAPI Specific Settings
Write-Host "Configuring Build Automation and Startup..." -ForegroundColor Cyan
az webapp config appsettings set --name $appName --resource-group $resourceGroup --settings `
    SCM_DO_BUILD_DURING_DEPLOYMENT=true `
    PYTHON_VERSION=3.11

# Set the Startup Command for FastAPI (assuming main.py and 'app = FastAPI()')
# We use Gunicorn with the Uvicorn worker for production stability
az webapp config set --name $appName --resource-group $resourceGroup --startup-file "gunicorn -w 4 -k uvicorn.workers.UvicornWorker --bind=0.0.0.0:8000 main:app"

# 4. Sync .env to Azure App Settings
if (Test-Path ".env") {
    Write-Host "Uploading Environment Variables..." -ForegroundColor Cyan
    Get-Content .env | Where-Object { $_ -match "=" -and $_ -notmatch "^#" } | ForEach-Object {
        az webapp config appsettings set --name $appName --resource-group $resourceGroup --settings $_
    }
}

# 5. Zip and Deploy
$zipFile = "deploy.zip"
if (Test-Path $zipFile) { Remove-Item $zipFile }

Write-Host "Creating deployment package..." -ForegroundColor Cyan
# Exclude the local venv and git folders to keep the zip small
Compress-Archive -Path * -DestinationPath $zipFile -Exclude ".git*", ".venv*", "__pycache__*", "deploy.ps1", $zipFile

Write-Host "Pushing code to Azure..." -ForegroundColor Cyan
az webapp deployment source config-zip --name $appName --resource-group $resourceGroup --src $zipFile

# Cleanup
Remove-Item $zipFile
Write-Host "Deployment Complete! Link: https://$appName.azurewebsites.net" -ForegroundColor Green