# Context-Engine Helm Chart

Self-hosted semantic code search and memory via MCP.

## Prerequisites

- Kubernetes 1.19+
- Helm 3.2.0+
- PV provisioner support (for persistent storage)
- Storage classes: `gp3-sc` (block) and `efs-sc` (shared filesystem) or equivalents

## Installation

### Quick Start

```bash
# Add local chart
helm install ce-dev ./deploy/helm/context-engine \
  --namespace context-engine \
  --create-namespace
```

### With Custom Values

```bash
# Copy the example values and customize
cp deploy/helm/context-engine/values-example.yaml deploy/kubernetes/values-mycompany.yaml
# Edit deploy/kubernetes/values-mycompany.yaml with your settings

# Install with custom values
helm install ce-mycompany ./deploy/helm/context-engine \
  -f ./deploy/kubernetes/values-mycompany.yaml \
  --namespace context-engine \
  --create-namespace
```

**Note**: Customer-specific values files should be stored in `deploy/kubernetes/` (gitignored) to keep sensitive configuration separate from the chart.

### From OCI Registry (when published)

```bash
helm install ce-prod oci://ghcr.io/context-engine-ai/charts/context-engine \
  --version 0.1.0 \
  --namespace context-engine \
  --create-namespace \
  -f custom-values.yaml
```

## Uninstall

```bash
helm uninstall ce-dev --namespace context-engine
```

## Configuration

### Global Settings

| Parameter | Description | Default |
|-----------|-------------|---------|
| `global.environment` | Environment name (dev, staging, prod) | `dev` |
| `global.team` | Team label for resources | `ai` |
| `global.appName` | Application name for labels | `context-engine` |

### Image

| Parameter | Description | Default |
|-----------|-------------|---------|
| `image.repository` | Image repository | `context-engine` |
| `image.tag` | Image tag (defaults to Chart appVersion) | `""` |
| `image.pullPolicy` | Pull policy | `IfNotPresent` |
| `image.pullSecrets` | Image pull secrets | `[]` |

### Namespace

| Parameter | Description | Default |
|-----------|-------------|---------|
| `namespace.create` | Create namespace | `true` |
| `namespace.name` | Namespace name | `context-engine` |

### Qdrant

| Parameter | Description | Default |
|-----------|-------------|---------|
| `qdrant.enabled` | Enable Qdrant | `true` |
| `qdrant.image.repository` | Qdrant image | `qdrant/qdrant` |
| `qdrant.image.tag` | Qdrant version | `latest` |
| `qdrant.replicas` | Number of replicas | `1` |
| `qdrant.service.httpPort` | HTTP port | `6333` |
| `qdrant.service.grpcPort` | gRPC port | `6334` |
| `qdrant.externalService.enabled` | Enable NodePort service | `true` |
| `qdrant.externalService.httpNodePort` | HTTP NodePort | `30333` |
| `qdrant.persistence.enabled` | Enable persistence | `true` |
| `qdrant.persistence.storageClassName` | Storage class | `gp3-sc` |
| `qdrant.persistence.size` | Storage size | `50Gi` |
| `qdrant.resources.requests.cpu` | CPU request | `1` |
| `qdrant.resources.requests.memory` | Memory request | `8Gi` |
| `qdrant.resources.limits.cpu` | CPU limit | `4` |
| `qdrant.resources.limits.memory` | Memory limit | `24Gi` |

### MCP Indexer HTTP

| Parameter | Description | Default |
|-----------|-------------|---------|
| `mcpIndexerHttp.enabled` | Enable indexer | `true` |
| `mcpIndexerHttp.replicas` | Number of replicas | `1` |
| `mcpIndexerHttp.service.port` | Service port | `8003` |
| `mcpIndexerHttp.externalService.nodePort` | NodePort | `30806` |
| `mcpIndexerHttp.autoscaling.enabled` | Enable HPA | `true` |
| `mcpIndexerHttp.autoscaling.minReplicas` | Min replicas | `1` |
| `mcpIndexerHttp.autoscaling.maxReplicas` | Max replicas | `4` |
| `mcpIndexerHttp.resources.requests.memory` | Memory request | `8Gi` |
| `mcpIndexerHttp.resources.limits.memory` | Memory limit | `16Gi` |

### MCP Memory HTTP

| Parameter | Description | Default |
|-----------|-------------|---------|
| `mcpMemoryHttp.enabled` | Enable memory service | `true` |
| `mcpMemoryHttp.replicas` | Number of replicas | `1` |
| `mcpMemoryHttp.service.port` | Service port | `8002` |
| `mcpMemoryHttp.externalService.nodePort` | NodePort | `30804` |
| `mcpMemoryHttp.autoscaling.enabled` | Enable HPA | `true` |
| `mcpMemoryHttp.autoscaling.minReplicas` | Min replicas | `1` |
| `mcpMemoryHttp.autoscaling.maxReplicas` | Max replicas | `3` |

### Upload Service

| Parameter | Description | Default |
|-----------|-------------|---------|
| `uploadService.enabled` | Enable upload service | `true` |
| `uploadService.replicas` | Number of replicas | `1` |
| `uploadService.service.port` | Service port | `8002` |
| `uploadService.service.nodePort` | NodePort | `30810` |
| `uploadService.autoscaling.enabled` | Enable HPA | `true` |

### Watcher

| Parameter | Description | Default |
|-----------|-------------|---------|
| `watcher.enabled` | Enable watcher | `true` |
| `watcher.replicas` | Number of replicas | `1` |
| `watcher.initContainers.waitForQdrant.enabled` | Wait for Qdrant | `true` |
| `watcher.initContainers.initCollection.enabled` | Init collection | `true` |

### Learning Reranker Worker

| Parameter | Description | Default |
|-----------|-------------|---------|
| `learningRerankerWorker.enabled` | Enable learning worker | `true` |
| `learningRerankerWorker.replicas` | Number of replicas | `1` |
| `learningRerankerWorker.autoscaling.enabled` | Enable HPA | `true` |

### Persistence (Shared PVCs)

| Parameter | Description | Default |
|-----------|-------------|---------|
| `persistence.codeRepos.enabled` | Enable code-repos PVC | `true` |
| `persistence.codeRepos.storageClassName` | Storage class | `efs-sc` |
| `persistence.codeRepos.size` | Storage size | `50Gi` |
| `persistence.codeMetadata.enabled` | Enable metadata PVC | `true` |
| `persistence.codeMetadata.size` | Storage size | `10Gi` |
| `persistence.codeModels.enabled` | Enable models PVC | `true` |
| `persistence.codeModels.size` | Storage size | `20Gi` |

### Ingress

| Parameter | Description | Default |
|-----------|-------------|---------|
| `ingress.enabled` | Enable ingress | `true` |
| `ingress.className` | Ingress class | `nginx` |
| `ingress.host` | Hostname | `""` |
| `ingress.tls` | TLS configuration | `[]` |
| `ingress.admin.enabled` | Enable admin ingress | `true` |

### Configuration (ConfigMap)

| Parameter | Description | Default |
|-----------|-------------|---------|
| `config.collectionName` | Qdrant collection name | `codebase` |
| `config.embeddingModel` | Embedding model | `BAAI/bge-base-en-v1.5` |
| `config.embeddingProvider` | Embedding provider | `fastembed` |
| `config.reranker.enabled` | Enable reranker | `1` |
| `config.reranker.model` | Reranker model | `jinaai/jina-reranker-v2-base-multilingual` |
| `config.refrag.enabled` | Enable ReFRAG | `1` |
| `config.refrag.runtime` | Decoder runtime | `glm` |
| `config.glm.apiBase` | GLM API base URL | `""` |
| `config.glm.apiKey` | GLM API key | `""` |
| `config.glm.model` | GLM model | `glm-4.7` |
| `config.auth.enabled` | Enable auth | `0` |
| `config.extraEnv` | Additional env vars | `{}` |

## Examples

### Minimal Installation (Dev/Testing)

```yaml
# values-minimal.yaml
qdrant:
  persistence:
    storageClassName: standard
    size: 10Gi

persistence:
  codeRepos:
    storageClassName: standard
    size: 10Gi
  codeMetadata:
    storageClassName: standard
    size: 5Gi
  codeModels:
    storageClassName: standard
    size: 5Gi

# Disable optional components
learningRerankerWorker:
  enabled: false

ingress:
  enabled: false
```

### Production with TLS

```yaml
# values-prod.yaml
image:
  repository: 535002867043.dkr.ecr.us-east-1.amazonaws.com/context-engine
  tag: v1.0.0

config:
  collectionName: production-codebase
  auth:
    enabled: "1"
    sharedToken: "your-token-here"

ingress:
  enabled: true
  className: alb
  host: ce.example.com
  annotations:
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/certificate-arn: arn:aws:acm:...
  tls:
    - hosts:
        - ce.example.com
      secretName: ce-tls
```

### With GLM Decoder

```yaml
# values-with-decoder.yaml
config:
  refrag:
    mode: "1"
    decoder: "1"
    decoderMode: prompt
    runtime: glm
  glm:
    apiBase: "https://api.z.ai/api/coding/paas/v4/"
    apiKey: "your-api-key"
    model: glm-4.7
```

### Multi-Repo Mode

```yaml
# values-multi-repo.yaml
config:
  multiRepoMode: "1"
  repoAutoFilter: "1"
  collectionName: multi-repo-collection

watcher:
  env:
    MULTI_REPO_MODE: "1"
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Ingress (nginx)                          │
│  /indexer → mcp-indexer-http    /memory → mcp-memory-http       │
│  /upload → upload-service       /qdrant → qdrant                │
└──────────────────────────────┬──────────────────────────────────┘
                               │
     ┌─────────────────────────┼─────────────────────────┐
     │                         │                         │
┌────┴────┐              ┌─────┴─────┐            ┌──────┴──────┐
│ Indexer │              │  Memory   │            │   Upload    │
│  HTTP   │              │   HTTP    │            │   Service   │
└────┬────┘              └─────┬─────┘            └──────┬──────┘
     │                         │                         │
     └─────────────────────────┼─────────────────────────┘
                               │
                         ┌─────┴─────┐
                         │  Qdrant   │
                         │(StatefulSet)
                         └───────────┘
                               ▲
     ┌─────────────────────────┼─────────────────────────┐
     │                         │                         │
┌────┴────┐              ┌─────┴─────┐            ┌──────┴──────┐
│ Watcher │              │ Learning  │            │   Shared    │
│         │              │  Worker   │            │    PVCs     │
└─────────┘              └───────────┘            └─────────────┘
```

## Storage Classes

The chart expects two types of storage:

1. **Block storage** (`gp3-sc`): For Qdrant StatefulSet (ReadWriteOnce)
2. **Shared filesystem** (`efs-sc`): For code-repos, metadata, models (ReadWriteMany)

### AWS EKS Example

```yaml
# gp3-sc.yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: gp3-sc
provisioner: ebs.csi.aws.com
parameters:
  type: gp3
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true

---
# efs-sc.yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: efs-sc
provisioner: efs.csi.aws.com
parameters:
  provisioningMode: efs-ap
  fileSystemId: fs-xxxxxxxxx
  directoryPerms: "700"
```

## Upgrading

```bash
helm upgrade ce-dev ./deploy/helm/context-engine \
  -f values-dev.yaml \
  --namespace context-engine
```

## Troubleshooting

### Check Pod Status

```bash
kubectl get pods -n context-engine
kubectl describe pod <pod-name> -n context-engine
```

### View Logs

```bash
# Indexer logs
kubectl logs -n context-engine -l app.kubernetes.io/component=mcp-indexer-http

# Watcher logs
kubectl logs -n context-engine -l app.kubernetes.io/component=watcher

# Qdrant logs
kubectl logs -n context-engine -l app.kubernetes.io/component=qdrant
```

### Common Issues

1. **Pods pending**: Check PVC status and storage class availability
2. **Watcher init fails**: Verify Qdrant is running and accessible
3. **Memory OOM**: Increase memory limits for indexer/memory services
4. **Ingress not working**: Verify ingress controller and annotations

## License

BUSL-1.1
