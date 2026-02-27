# DGX Spark Kubeadm Deployment

Ansible playbooks and Helm charts for deploying a single-node Kubernetes cluster with GPU time-slicing on an NVIDIA DGX Spark, then serving LLMs via Ollama/KServe and a GraphRAG pipeline via LightRAG.

## Prerequisites

- NVIDIA DGX Spark (GB10, ARM64) with NVIDIA drivers and `nvidia-ctk` installed
- Ubuntu with `containerd.io` compatible packages
- Ansible installed on the host
- Internet access for downloading packages, container images, and model weights

## Quick Start

```bash
# 1. Install single-node Kubernetes 1.34 with GPU operator and time-slicing
ansible-playbook -i inventory.ini install-k8s.yml --become

# 2. Download quantized model weights
ansible-playbook -i inventory.ini download-models.yml --become

# 3. Deploy LLMs (cert-manager, KServe, and the llm-serving Helm chart)
ansible-playbook -i inventory.ini deploy-models.yml --become

# 4. (Optional) Deploy GraphRAG stack
ansible-playbook -i inventory.ini deploy-graphrag.yml --become

# 5. (Optional) Install OpenCode IDE with local LLM backends
ansible-playbook -i inventory.ini install-opencode.yml --become
```

## What Gets Installed

**install-k8s.yml** sets up:
- Kubernetes 1.34 via kubeadm (single-node, control-plane taint removed)
- Containerd with NVIDIA runtime as default
- Flannel CNI (pod CIDR `10.244.0.0/16`)
- NVIDIA GPU Operator with time-slicing (5 virtual GPUs from 1 physical GPU)
- Helm 3
- Longhorn distributed storage (storage classes: `longhorn`, `longhorn-models`)
- A 2-pod GPU sharing validation test

**download-models.yml** pulls models into Longhorn PVCs using temporary containers:
- `qwen3-coder-next:q4_K_M` — primary code generation model
- `deepseek-r1:32b` — reasoning model (with tools-enabled variant)
- `qwen3-embedding:0.6b` — embedding model for GraphRAG
- `llama3.1:8b` — extraction model for GraphRAG
- `BAAI/bge-reranker-v2-m3` — reranking model for GraphRAG (HuggingFace)

**deploy-models.yml** deploys:
- cert-manager (KServe prerequisite)
- KServe in RawDeployment mode
- `llm-serving` Helm chart with one Ollama pod per model

**deploy-graphrag.yml** deploys:
- Builds custom container images via `nerdctl` into containerd
- `graphrag` Helm chart with LightRAG, Neo4j, PostgreSQL+pgvector, dedicated Ollama instances for embedding/extraction, a vLLM reranker, and a tree-sitter code preprocessor

**install-opencode.yml** sets up:
- OpenCode IDE configured to use the local LLM endpoints
- NodePort services exposing models on the host (Qwen=31434, DeepSeek=31435)

## Accessing Models

LLM serving models expose an OpenAI-compatible API on port 11434:

```bash
# From within the cluster
curl http://qwen3-coder-next-predictor.llm-serving.svc.cluster.local:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3-coder-next","messages":[{"role":"user","content":"Hello"}]}'

# From the host (after install-opencode.yml creates NodePort services)
curl http://localhost:31434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3-coder-next","messages":[{"role":"user","content":"Hello"}]}'
```

GraphRAG endpoints (after deploy-graphrag.yml):

| Service | Host URL | Cluster URL |
|---|---|---|
| LightRAG API | http://localhost:31436 | http://lightrag.graphrag.svc.cluster.local:9621 |
| Neo4j Browser | http://localhost:31474 | http://neo4j.graphrag.svc.cluster.local:7474 |
| Code Preprocessor | http://localhost:31490 | http://code-preprocessor.graphrag.svc.cluster.local:8090 |

## Helm Charts

### charts/llm-serving

Supports two modes via `values.yaml`:

- **KServe mode** (`kserve: true`, default) — creates `InferenceService` resources
- **Plain mode** (`kserve: false`) — creates standard `Deployment` + `Service` resources

```bash
# Render templates locally
helm template llm-serving charts/llm-serving

# Override values at deploy time
ansible-playbook -i inventory.ini deploy-models.yml --become \
  -e use_kserve=false
```

### charts/graphrag

Deploys a full GraphRAG pipeline:

- **ollama-embed** — Ollama serving qwen3-embedding for vector embeddings
- **ollama-extract** — Ollama serving llama3.1:8b for entity extraction
- **vllm-rerank** — vLLM serving BAAI/bge-reranker-v2-m3 for reranking
- **LightRAG** — RAG server with workspace multitenancy (set `LIGHTRAG-WORKSPACE` header per request)
- **Neo4j** — Graph storage for extracted entities and relationships
- **PostgreSQL + pgvector** — Vector/KV storage for embeddings and document status
- **code-preprocessor** — FastAPI service using tree-sitter to parse source code before ingestion

## Custom Applications

### apps/code-preprocessor

FastAPI service that parses code files using tree-sitter. Endpoints:
- `POST /parse` — Parse a single code file, return structured document
- `POST /parse/batch` — Parse multiple code files
- `POST /ingest` — Unified gateway: code files go through tree-sitter, documents are forwarded directly to LightRAG

Supports: Python, JavaScript/TypeScript, Go, Rust, Java, C/C++.

### apps/lightrag

Custom LightRAG entrypoint (`workspace_patch.py`) that adds per-request workspace multitenancy. Uses a Python contextvar descriptor to scope all storage backends (Neo4j, pgvector, KV) by the `LIGHTRAG-WORKSPACE` request header.

## Memory Budget

DGX Spark uses 128GB unified memory shared between GPU VRAM and system RAM. Pod memory limits must cover model weights, KV cache, and Ollama overhead.

**LLM Serving:**

| Model | Memory Limit | GPU | Context Length |
|---|---|---|---|
| qwen3-coder-next | 120Gi | 1 time-slice | 131072 |
| deepseek-r1-distill-32b | 120Gi | 1 time-slice | 32768 |

**GraphRAG (additional):**

| Component | Memory Limit | GPU |
|---|---|---|
| ollama-embed (qwen3-embedding) | 8Gi | 1 time-slice |
| ollama-extract (llama3.1:8b) | 16Gi | 1 time-slice |
| vllm-rerank (bge-reranker-v2-m3) | 8Gi | 1 time-slice |
| Neo4j | 8Gi | — |
| PostgreSQL | 2Gi | — |
| LightRAG | 4Gi | — |
| code-preprocessor | 1Gi | — |

## Teardown

```bash
# Remove individual stacks (preserves data on disk)
ansible-playbook -i inventory.ini remove-models.yml --become
ansible-playbook -i inventory.ini remove-graphrag.yml --become

# Remove the entire Kubernetes cluster
ansible-playbook -i inventory.ini remove-k8s.yml --become
```

`remove-models.yml` and `remove-graphrag.yml` uninstall Helm releases and delete namespaces but preserve model and data files on disk. `remove-k8s.yml` removes the entire cluster, packages, and network configuration; containerd and the NVIDIA runtime are left installed.
