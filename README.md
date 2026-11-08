# DGX Spark Kubeadm Deployment

Ansible playbooks and Helm charts for deploying a single-node Kubernetes cluster with GPU time-slicing on an NVIDIA DGX Spark, then serving LLMs via Ollama/KServe and a memory-aware GraphRAG pipeline via LightRAG with async document ingestion and an OpenAI-compatible orchestrator.

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

# 6. (Optional) Protect the model volumes and schedule a nightly snapshot
ansible-playbook -i inventory.ini backup-models.yml --become \
  -e backup_schedule="0 3 * * *"
```

## Optional Operator Layer

`automation/dgx10-ansible/` is an optional Ansible framework that wraps this repository (pinned at `4a0c971`). It does not replace the playbooks above — it calls them — and adds the operator-facing layer:

- a model catalog and fit planner that prices weights + KV cache against the 5 time-sliced GPU slots
- per-model OpenAI-compatible verification, fixed report cards and a read-only `doctor`
- an OpenAI-compatible gateway (LiteLLM) in front of every model, with optional TLS and key rotation
- Prometheus/Grafana with a GPU dashboard, digest-pinned GitOps rendering, Argo CD, and helm upgrade/rollback
- backup/restore, multi-node join/leave, policy enforcement, an offline bundle and CI

It keeps its own inventory and variables, so the playbooks in this repository continue to work exactly as documented above. Run it from `automation/dgx10-ansible/`; its `README.md` is the authoritative guide.

## What Gets Installed

**install-k8s.yml** sets up:
- Kubernetes 1.34 via kubeadm (single-node, control-plane taint removed)
- Containerd with NVIDIA runtime as default
- Flannel CNI (pod CIDR `10.244.0.0/16`)
- NVIDIA GPU Operator with time-slicing (5 virtual GPUs from 1 physical GPU)
- Helm 3
- Longhorn distributed storage (storage classes: `longhorn`, `longhorn-models`) with multipathd blacklisting to prevent device conflicts
- A 2-pod GPU sharing validation test
- (Optional, `-e install_policy_engine=true`) Calico in policy-only mode beside Flannel, so `NetworkPolicy` is enforced

**download-models.yml** pulls models into Longhorn PVCs using temporary containers. Model names, tags, PVC sizes, and download sources are defined in `group_vars/k8s.yml` (single source of truth). Uses block/rescue for resilient downloads (failures log warnings instead of aborting), cleans up stale pods from previous runs, and adds Helm management labels to PVCs:
- `qwen3-coder-next:q4_K_M` — primary code generation model
- `deepseek-r1:32b` — reasoning model (with tools-enabled variant)
- `qwen3-embedding:0.6b` — embedding model for GraphRAG
- `qwen3:8b` — extraction/summarization model for GraphRAG
- `BAAI/bge-reranker-v2-m3` — reranking model for GraphRAG (HuggingFace)

Any models declared under `extra_models` in `group_vars/k8s.yml` are pulled into their own PVCs by the same flow. See [Serving Additional Models](#serving-additional-models).

**deploy-models.yml** deploys:
- cert-manager (KServe prerequisite)
- KServe in RawDeployment mode
- `llm-serving` Helm chart with one Ollama pod per model, including any `extra_models` entries merged into the chart values

**deploy-graphrag.yml** deploys:
- Builds custom container images via `nerdctl` into containerd (`graphrag-code-preprocessor`, `graphrag-lightrag`, `graphrag-orchestrator`, `graphrag-ingest-worker`, `graphrag-ingestion-ui`)
- `graphrag` Helm chart with:
  - LightRAG, Neo4j, PostgreSQL+pgvector, dedicated Ollama instances for embedding/extraction, a vLLM reranker, and a tree-sitter code preprocessor
  - **Orchestrator** — OpenAI-compatible chat proxy with 3-tier memory (working/recall/archival), multi-backend LLM routing, workspace management, and document lifecycle APIs
  - **Ingest Worker** — NATS JetStream consumer for async document and codebase processing with LightRAG indexing status polling
  - **Ingestion UI** — React SPA for workspace dashboards, drag-and-drop document upload, job monitoring, knowledge graph visualization, and multi-mode query search
  - **NATS** — JetStream message queue for ingestion jobs
  - **Redis** — Working memory store for session state with TTL

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
| Ingestion UI | http://localhost:31300 | http://ingestion-ui.graphrag.svc.cluster.local:8080 |
| Orchestrator | http://localhost:31800 | http://orchestrator.graphrag.svc.cluster.local:8100 |
| LightRAG API | http://localhost:31436 | http://lightrag.graphrag.svc.cluster.local:9621 |
| Neo4j Browser | http://localhost:31474 | http://neo4j.graphrag.svc.cluster.local:7474 |
| Code Preprocessor | http://localhost:31490 | http://code-preprocessor.graphrag.svc.cluster.local:8090 |

The orchestrator exposes the same `/v1/chat/completions` interface as the LLM backends, so clients can point at it as a drop-in replacement that adds memory augmentation and model routing.

## Serving Additional Models

The `coding` and `reasoning` entries in `group_vars/k8s.yml` are the pair the rest of the stack assumes. To serve more Ollama models beside them, add entries to `extra_models` in the same file — nothing else has to change:

```yaml
extra_models:
  qwen3-14b:
    name: qwen3-14b
    tag: "qwen3:14b"
    source: ollama
    namespace: llm-serving
    pvc: ollama-qwen3-14b
    size: 20Gi
```

Then re-run the two model playbooks:

```bash
ansible-playbook -i inventory.ini download-models.yml --become
ansible-playbook -i inventory.ini deploy-models.yml --become
```

`download-models.yml` creates the PVC, pulls the weights, and verifies their digests exactly as it does for the base pair. `deploy-models.yml` merges the extra entries into the `llm-serving` chart values (writing them to `/tmp/llm-serving-values.yaml`) and runs one `helm upgrade --install`, so the chart still sees a single release with a single `models` map. Each extra model gets its own `InferenceService`, pod, and `ollama-<name>` PVC.

Constraints worth knowing:

- `pvc` must be `ollama-<name>` and `namespace` must be `llm-serving`; the playbook asserts both, so a typo fails before anything is pulled.
- `source` must be `ollama` — the chart serves Ollama only. HuggingFace models (`extract`, `embed`, `reranker`) stay in the GraphRAG chart.
- Each model requests one `nvidia.com/gpu`, and the cluster grants 5 time-slices. The playbook warns when the base pair plus extras exceeds that budget; extra pods then stay `Pending` until a slice frees up.
- Optional chart fields (`image`, `port`, `numCtx`, `numParallel`, `resources`, `storageClass`) default to the values in `charts/llm-serving/values.yaml`; `chart_values` merges any other chart option verbatim.
- The base pair is still passed with `--set`, which wins over the values file. Extra models are not exposed as NodePorts; add a Service if you need one from the host.

Unlisted models remain disabled (`enabled: false`) in the chart, and weights on their PVCs are kept — Helm honours `helm.sh/resource-policy: keep` when pruning.

## Backup and Restore

`backup-models.yml` snapshots or backs up every PVC declared in `group_vars/k8s.yml` (`models` and `extra_models`):

```bash
# On-cluster snapshot of each model volume
ansible-playbook -i inventory.ini backup-models.yml --become

# Backup to the configured Longhorn backup target (Settings -> backup-target)
ansible-playbook -i inventory.ini backup-models.yml --become -e backup_action=backup

# Keep taking snapshots every night without a playbook run
ansible-playbook -i inventory.ini backup-models.yml --become \
  -e backup_schedule="0 3 * * *"
```

A snapshot stays on the node and protects against a bad write; a backup needs a backup target and survives losing the node. Neither replaces `download-models.yml`, which is still the way to rebuild a volume from the exact tags.

`backup_schedule` installs a Longhorn `RecurringJob` (`backup_group`, default `dgx-models`) and labels the model volumes into its group, so protection does not depend on someone remembering to run the playbook. `backup_retain` (default `5`) bounds how many are kept.

A restore never overwrites the live volume. It creates a new Longhorn volume from the snapshot or backup, pre-binds a new PV/PVC, and waits for `Bound`:

```bash
ansible-playbook -i inventory.ini restore-models.yml --become \
  -e restore_name=dgx-model-ollama-qwen3-coder-next
```

Useful overrides: `restore_namespace` (default `llm-serving`), `restore_pvc` (default `<source>-restored-<timestamp>`), `restore_size` (default the source PVC's size), `restore_kind` (`auto`, `snapshot` or `backup`). The restored claim can be mounted by a pod to copy files out; delete it when done.

## Multi-Node Clusters

`install-k8s.yml` still builds a single-node cluster. Additional nodes join with `join-k8s.yml`, using an inventory that names the control plane and the workers (`inventory-multinode.ini` is an example):

```ini
[k8s]
dgx-control ansible_host=10.0.0.10

[workers]
dgx-worker-1 ansible_host=10.0.0.11
```

```bash
ansible-playbook -i inventory-multinode.ini join-k8s.yml --become
```

The workers must already have the same prerequisites as the control plane — packages, kernel modules and sysctls, containerd with the NVIDIA runtime, `kubeadm`/`kubelet`/`kubectl`, swap off. `join-k8s.yml` checks for them and fails with what is missing rather than joining a node that cannot run GPU pods. The token is created on the control plane (`control_plane_host`, default `localhost`) and the play waits for every joined node to be `Ready`.

To remove a worker:

```bash
ansible-playbook -i inventory-multinode.ini leave-k8s.yml --become \
  -e leave_confirm=true
```

It drains the node, deletes its Node object, runs `kubeadm reset`, and clears the CNI and kubelet state so the host can rejoin. The control plane is never touched. `leave_drain=false` skips the drain.

## Policy Enforcement

The default CNI is Flannel, which accepts `NetworkPolicy` objects and does not enforce them. Re-run the cluster install with:

```bash
ansible-playbook -i inventory.ini install-k8s.yml --become \
  -e install_policy_engine=true
```

This installs Calico in policy-only mode beside Flannel (`calico_version`, default `v3.29.3`): pod routing stays with Flannel, but Felix enforces policies from then on. Without the flag, `install-k8s.yml` says plainly that policies are declarative only.

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

Deploys the full GraphRAG pipeline plus the orchestration and ingestion layer:

- **ollama-embed** — Ollama serving qwen3-embedding for vector embeddings
- **ollama-extract** — Ollama serving qwen3:8b for entity extraction and summarization
- **vllm-rerank** — vLLM serving BAAI/bge-reranker-v2-m3 for reranking
- **LightRAG** — RAG server with workspace multitenancy (set `LIGHTRAG-WORKSPACE` header per request)
- **Neo4j** — Graph storage for extracted entities and relationships
- **PostgreSQL + pgvector** — Vector/KV storage for embeddings, document status, session history, and job tracking
- **code-preprocessor** — FastAPI service using tree-sitter to parse source code and extract content from PDFs before ingestion
- **orchestrator** — OpenAI-compatible memory proxy with 3-tier memory (Redis working memory, PostgreSQL recall memory, LightRAG archival memory) and routing to Qwen/DeepSeek backends
- **ingest-worker** — NATS JetStream consumer that asynchronously processes document and codebase ingestion jobs, with LightRAG pipeline status polling
- **ingestion-ui** — React SPA for managing workspaces, uploading documents, monitoring jobs, visualizing knowledge graphs, and querying the RAG pipeline
- **NATS** — JetStream message queue for async ingestion
- **Redis** — Working memory and session state with TTL-based eviction

## Custom Applications

### apps/orchestrator

OpenAI-compatible chat proxy (`/v1/chat/completions`) with a 3-tier memory system:

- **Working memory** (Redis) — current conversation turns for the active session, TTL-based expiry
- **Recall memory** (PostgreSQL + pgvector) — full message history with vector similarity search over session summaries
- **Archival memory** (LightRAG) — long-term graph-based knowledge retrieved via RAG queries

Automatically summarizes sessions and promotes context between tiers based on configurable turn thresholds (`promote_after_turns`, `archival_after_turns`). Routes requests to Qwen (coding) or DeepSeek (reasoning) backends. Additional endpoints: `/v1/documents/ingest` (async via NATS), `DELETE /v1/documents/{doc_id}` (cascading deletion to LightRAG), `/v1/workspaces` (list with aggregate stats), `DELETE /v1/workspaces/{workspace}` (full workspace cleanup), `/v1/models`, session and job management.

### apps/ingest-worker

NATS JetStream pull consumer that processes async ingestion jobs. Listens on `ingest.document` and `ingest.codebase` subjects. Sends files to the code preprocessor for parsing, tracks job status in PostgreSQL (queued → started → indexing → completed/failed), and handles retries with configurable max redeliveries. After processing, polls LightRAG's pipeline status (`indexing_poll_timeout`, `indexing_poll_interval`) before marking jobs complete. Supports archive extraction (tar.gz, zip) for codebase ingestion with a 2000-file/1MB-per-file limit.

### apps/code-preprocessor

FastAPI service that parses code files using tree-sitter and extracts content from PDFs. Attaches `file_source` metadata to all LightRAG ingestion calls for document provenance tracking. Endpoints:
- `POST /parse` — Parse a single code file, return structured document
- `POST /parse/batch` — Parse multiple code files
- `POST /ingest` — Unified gateway: code files go through tree-sitter, PDFs through pdfplumber text extraction and code block detection, then results are forwarded to LightRAG

Supports: Python, JavaScript/TypeScript, Go, Rust, Java, C/C++.

### apps/lightrag

Custom LightRAG entrypoint (`workspace_patch.py`) that adds per-request workspace multitenancy. Uses a Python contextvar descriptor to scope all storage backends (Neo4j, pgvector, KV) by the `LIGHTRAG-WORKSPACE` request header.

### apps/ingestion-ui

React 19 SPA (Vite + Tailwind CSS 4) served by Nginx with reverse-proxy to orchestrator and LightRAG. Features:
- **Dashboard** — Workspace overview cards with document counts, job statuses, and workspace management (delete/clear)
- **Ingest** — Drag-and-drop file upload with auto-detection of archives (tar.gz/zip) as codebase ingestion
- **Jobs** — Filterable job list with auto-polling (3s interval) and expandable detail rows
- **Documents** — Document list with download/delete actions and orphaned LightRAG document detection
- **Graph** — Interactive 2D force-directed knowledge graph visualization with query filtering and node inspection
- **Query** — Multi-mode search (naive/mix/local/global/hybrid) with LLM "Explain" and collapsible result sections

Nginx proxies `/api/` to the orchestrator and `/lightrag/` to LightRAG. Vite dev config proxies to NodePort endpoints (31800, 31436) for local development.

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
| ollama-extract (qwen3:8b) | 16Gi | 1 time-slice |
| vllm-rerank (bge-reranker-v2-m3) | 8Gi | 1 time-slice |
| Neo4j | 8Gi | — |
| PostgreSQL | 2Gi | — |
| LightRAG | 4Gi | — |
| Orchestrator | 1Gi | — |
| Ingest Worker | 512Mi | — |
| code-preprocessor | 1Gi | — |
| Ingestion UI | 128Mi | — |
| Redis | 512Mi | — |
| NATS | 256Mi | — |

## Teardown

```bash
# Remove individual stacks (preserves data on disk)
ansible-playbook -i inventory.ini remove-models.yml --become
ansible-playbook -i inventory.ini remove-graphrag.yml --become

# Remove the entire Kubernetes cluster
ansible-playbook -i inventory.ini remove-k8s.yml --become
```

`remove-models.yml` and `remove-graphrag.yml` uninstall Helm releases and delete namespaces but preserve model and data files on disk. `remove-k8s.yml` removes the entire cluster, packages, and network configuration; containerd and the NVIDIA runtime are left installed.

## License

[MIT](LICENSE) © 2026 Martin Forde <mforde84@gmail.com>, [Blik Labs](https://bliklabs.com).
