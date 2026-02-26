# DGX Spark Kubeadm Deployment

Ansible playbooks and Helm chart for deploying a single-node Kubernetes cluster with GPU time-slicing on an NVIDIA DGX Spark, then serving LLMs via Ollama and KServe.

## Prerequisites

- NVIDIA DGX Spark (GB10, ARM64) with NVIDIA drivers and `nvidia-ctk` installed
- Ubuntu with `containerd.io` compatible packages
- Ansible installed on the host
- Internet access for downloading packages, container images, and model weights

## Quick Start

```bash
# 1. Install single-node Kubernetes 1.34 with GPU operator and time-slicing
ansible-playbook -i inventory.ini install-k8s.yml --become

# 2. Download quantized model weights from HuggingFace
ansible-playbook -i inventory.ini download-models.yml --become

# 3. Deploy LLMs (cert-manager, KServe, and the llm-serving Helm chart)
ansible-playbook -i inventory.ini deploy-models.yml --become
```

## What Gets Installed

**install-k8s.yml** sets up:
- Kubernetes 1.34 via kubeadm (single-node, control-plane taint removed)
- Containerd with NVIDIA runtime as default
- Flannel CNI (pod CIDR `10.244.0.0/16`)
- NVIDIA GPU Operator with time-slicing (4 virtual GPUs from 1 physical GPU)
- Helm 3
- A 2-pod GPU sharing validation test

**download-models.yml** downloads Q4_K_M quantized GGUFs to `/misc/models/`:
- `qwen3-coder-next` — from Ollama registry (pulled at deploy time)
- `deepseek-r1-distill-32b` — from HuggingFace (bartowski/DeepSeek-R1-Distill-Qwen-32B-GGUF)

**deploy-models.yml** deploys:
- cert-manager (KServe prerequisite)
- KServe in RawDeployment mode
- `llm-serving` Helm chart with one Ollama pod per model

## Accessing Models

Models are served on port 11434 with an OpenAI-compatible API:

```bash
curl http://qwen3-coder-next.llm-serving.svc.cluster.local:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3-coder-next","messages":[{"role":"user","content":"Hello"}]}'
```

## Helm Chart

The `charts/llm-serving` chart supports two modes via `values.yaml`:

- **KServe mode** (`kserve: true`, default) — creates `InferenceService` resources
- **Plain mode** (`kserve: false`) — creates standard `Deployment` + `Service` resources

```bash
# Render templates locally
helm template llm-serving charts/llm-serving --set modelsHostPath=/misc/models

# Override values at deploy time
ansible-playbook -i inventory.ini deploy-models.yml --become \
  -e use_kserve=false
```

## Memory Budget

DGX Spark uses 128GB unified memory shared between GPU VRAM and system RAM. Current allocation:

| Model | Memory Limit | GPU | Parallel Requests |
|---|---|---|---|
| qwen3-coder-next | 72Gi | 1 time-slice | 2 |
| deepseek-r1-distill-32b | 48Gi | 1 time-slice | 4 |

## Teardown

```bash
ansible-playbook -i inventory.ini remove-k8s.yml --become
```

This removes the entire Kubernetes cluster, packages, and network configuration. Containerd and the NVIDIA runtime are left installed.
