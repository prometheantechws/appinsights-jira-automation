@description('An environment name used to construct resource names')
param environmentName string

@description('Location for all resources')
param location string = resourceGroup().location

@description('Tenant ID for the subscription')
param tenantId string = subscription().tenantId

@description('Name of the Container App Environment')
param containerAppEnvName string = '${environmentName}-jira-container-env'

@description('Name of the Storage Account')
param storageAccountName string = 'myjirastrg123${environmentName}'

@description('Name of the Key Vault')
param keyVaultName string = 'jira-123-${environmentName}'

// Create the Storage Account with updated API version
resource storageAccount 'Microsoft.Storage/storageAccounts@2024-01-01' = {
  name: storageAccountName
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    networkAcls: {
      defaultAction: 'Allow'
      bypass: 'AzureServices'
    }
    encryption: {
      keySource: 'Microsoft.Storage'
      services: {
        blob: {
          enabled: true
        }
        file: {
          enabled: true
        }
        queue: {
          enabled: true
        }
        table: {
          enabled: true
        }
      }
    }
  }
}

// Create the Container App Environment with updated API version
resource containerAppEnv 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: containerAppEnvName
  location: location
  properties: {
    zoneRedundant: false
  }
}

// Key Vault resource
resource keyVault 'Microsoft.KeyVault/vaults@2024-12-01-preview' = {
  name: keyVaultName
  location: location
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: tenantId
    enableRbacAuthorization: true // Enable RBAC for authorization
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    networkAcls: {
      defaultAction: 'Allow'
      bypass: 'AzureServices'
    }
  }
}

// Create secrets in the existing Key Vault
resource secretAppInsightsAppId 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'APPINSIGHTS-APP-ID'
  properties: {
    value: 'APPINSIGHTS-APP-ID'
  }
  dependsOn: [keyVault]
}

resource secretAppInsightsApiKey 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'APPINSIGHTS-API-KEY'
  properties: {
    value: 'APPINSIGHTS-API-KEY'
  }
  dependsOn: [keyVault]
}

resource secretJiraEmail 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'JIRA-EMAIL'
  properties: {
    value: 'JIRA-EMAIL'
  }
  dependsOn: [keyVault]
}

resource secretJiraToken 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'JIRA-TOKEN'
  properties: {
    value: 'JIRA-TOKEN'
  }
  dependsOn: [keyVault]
}

resource secretJiraUrl 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'JIRA-URL'
  properties: {
    value: 'JIRA-URL'
  }
  dependsOn: [keyVault]
}

resource secretJiraProject 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'JIRA-PROJECT'
  properties: {
    value: 'JIRA-PROJECT'
  }
  dependsOn: [keyVault]
}

resource secretAzureConnString 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'AZURE-CONNECTION-STRING'
  properties: {
    value: 'AZURE-CONNECTION-STRING'
  }
  dependsOn: [keyVault]
}


// Add outputs for all resources
output location string = location
output keyVaultName string = keyVault.name
output resourceGroupName string = resourceGroup().name
output keyVaultResourceId string = keyVault.id
output storageAccountName string = storageAccount.name
output containerAppEnvName string = containerAppEnv.name
