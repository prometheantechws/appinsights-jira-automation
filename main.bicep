@description('Location for all resources')
param location string = resourceGroup().location

@description('An environment name used to construct resource names')
param environmentName string

@description('Name of the Container App Environment (created in infra.bicep)')
param containerAppEnvName string = '${environmentName}-container-env'

@description('Name of the Container App')
param containerAppName string = '${environmentName}-my-jira-api'

@description('Global resource group name that contains shared resources')
param globalResourceGroupName string = 'Apeirosai-Test-RG'

@description('Name of the ACR')
param acrName string = 'myacr123'

@description('Image name in ACR')
param imageName string = 'jirakv'

@description('Image tag for the container')
param imageTag string = '1'

@description('Image URI for the container (fully qualified)')
param imageUri string = '${acrName}.azurecr.io/${imageName}:${imageTag}'

@description('Port to target for container ingress')
param targetPort int = 5000

@description('CPU cores for the container')
param cpuCore string = '0.25'

@description('Memory size (in Gi) for the container')
param memorySize string = '0.5'

@description('Minimum number of replicas for the container app')
param minReplicas int = 0

@description('Maximum number of replicas for the container app')
param maxReplicas int = 1

@description('Name of the Key Vault (created in infra.bicep)')
param keyVaultName string = 'jira-${environmentName}'

// Reference the existing Container App Environment
resource containerAppEnv 'Microsoft.App/managedEnvironments@2022-03-01' existing = {
  name: containerAppEnvName
}

// Reference the container registry in the global resource group
resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-06-01-preview' existing = {
  scope: resourceGroup(globalResourceGroupName)
  name: acrName
}

// Create a User Assigned Managed Identity
resource containerAppIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-07-31-preview' = {
  name: '${containerAppName}-identity'
  location: location
}

// Assign the Key Vault Secrets User role to the managed identity
var keyVaultSecretsUserRoleDefinitionId = resourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')

resource KeyVaultRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: resourceId('Microsoft.KeyVault/vaults', keyVaultName)
  name: guid(keyVaultSecretsUserRoleDefinitionId, containerAppIdentity.id, resourceGroup().id)
  properties: {
    roleDefinitionId: keyVaultSecretsUserRoleDefinitionId
    principalId: containerAppIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// Create the Container App with the user-assigned identity
resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: containerAppName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${containerAppIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: containerAppEnv.id
    configuration: {
      secrets: [
        {
          name: 'acr-password'
          value: containerRegistry.listCredentials().passwords[0].value
        }
      ]
      registries: [
        {
          server: '${acrName}.azurecr.io'
          username: containerRegistry.listCredentials().username
          passwordSecretRef: 'acr-password'
        }
      ]
      ingress: {
        external: true
        targetPort: targetPort
        allowInsecure: false
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
        corsPolicy: {
          allowCredentials: true
          allowedHeaders: [
            '*'
          ]
          allowedMethods: [
            '*'
          ]
          allowedOrigins: [
            '*'
          ]
        }
      }
    }
    template: {
      containers: [
        {
          name: containerAppName
          image: imageUri
          resources: {
            cpu: json(cpuCore)
            memory: '${memorySize}Gi'
          }
          env: [
            {
              name: 'AZURE_CLIENT_ID'
              value: containerAppIdentity.properties.clientId
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
        rules: [
          {
            name: 'http-scale-rule'
            http: {
              metadata: {
                concurrentRequests: '100'
              }
            }
          }
        ]
      }
    }
  }
}
