#!/usr/bin/env bash
# Read-only diagnosis of a DGX Spark serving stack.
#
# Output is one tab-separated line per finding:
#   LEVEL <TAB> CHECK <TAB> DETAIL <TAB> FIX
# LEVEL is OK, WARN or ERROR. Exit status is the number of ERROR lines (max 99).
# The role that runs this turns ERROR into a failed play; nothing here mutates
# the cluster.
set -uo pipefail

NS="${DGX_NAMESPACE:-llm-serving}"
GPU_SLICES="${DGX_MAX_GPU_SLICES:-5}"
KUBECTL="${KUBECTL:-kubectl}"
errors=0

emit() {
  local level="$1" check="$2" detail="$3" fix="$4"
  detail="$(printf '%s' "$detail" | tr '\t\n' '  ')"
  fix="$(printf '%s' "$fix" | tr '\t\n' '  ')"
  printf '%s\t%s\t%s\t%s\n' "$level" "$check" "$detail" "$fix"
  if [ "$level" = "ERROR" ]; then
    errors=$((errors + 1))
  fi
}

if ! command -v "$KUBECTL" >/dev/null 2>&1; then
  emit ERROR kubectl "kubectl not found on PATH" "install kubectl or set KUBECTL"
  exit 1
fi

if ! "$KUBECTL" get nodes >/dev/null 2>&1; then
  emit ERROR api "cluster API is unreachable" "check KUBECONFIG and that the control plane is running"
  echo "SUMMARY	errors=${errors}" >&2
  exit 1
fi

# ── nodes ────────────────────────────────────────────────────────────
total_nodes=$("$KUBECTL" get nodes --no-headers 2>/dev/null | wc -l | tr -d ' ')
ready_nodes=$("$KUBECTL" get nodes --no-headers 2>/dev/null | grep -c ' Ready ' || true)
if [ "$ready_nodes" -ge 1 ]; then
  emit OK nodes "${ready_nodes}/${total_nodes} Ready" ""
else
  emit ERROR nodes "no Ready nodes" "inspect kubelet: systemctl status kubelet"
fi

if "$KUBECTL" get nodes --no-headers 2>/dev/null | grep -q 'NotReady'; then
  emit WARN nodes "a node is NotReady" "kubectl describe node <name>; check kubelet and CNI"
fi

# ── GPU operator and time slicing ────────────────────────────────────
if ! "$KUBECTL" get namespace gpu-operator >/dev/null 2>&1; then
  emit ERROR gpu-operator "namespace gpu-operator is missing" "run install-k8s.yml with the GPU Operator enabled"
else
  not_ready=$("$KUBECTL" -n gpu-operator get pods --no-headers 2>/dev/null \
    | grep -Ev 'Running|Completed' | wc -l | tr -d ' ')
  if [ "$not_ready" -eq 0 ]; then
    emit OK gpu-operator "all pods Running or Completed" ""
  else
    emit ERROR gpu-operator "${not_ready} pod(s) not Running" "kubectl -n gpu-operator get pods; describe the failing pod"
  fi
  if "$KUBECTL" -n gpu-operator get configmap -o name 2>/dev/null | grep -qi 'time-slicing'; then
    emit OK time-slicing "time-slicing ConfigMap present" ""
  else
    emit ERROR time-slicing "no time-slicing ConfigMap in gpu-operator" "re-run install-k8s.yml; it creates the time-slicing config"
  fi
fi

if command -v nvidia-smi >/dev/null 2>&1; then
  if nvidia-smi -L >/dev/null 2>&1; then
    emit OK driver "$(nvidia-smi -L | head -1)" ""
  else
    emit ERROR driver "nvidia-smi failed" "reinstall the DGX Spark GPU driver"
  fi
else
  emit WARN driver "nvidia-smi not on PATH" "run this script on the DGX host, not the controller"
fi

# ── storage ──────────────────────────────────────────────────────────
if "$KUBECTL" get storageclass longhorn-models >/dev/null 2>&1; then
  emit OK storageclass "longhorn-models exists" ""
else
  emit ERROR storageclass "longhorn-models StorageClass is missing" "re-run install-k8s.yml or create the StorageClass"
fi

unbound=$("$KUBECTL" -n "$NS" get pvc --no-headers 2>/dev/null \
  | awk '$2 != "Bound" {print $1}' | tr '\n' ' ')
if [ -z "${unbound// /}" ]; then
  emit OK pvc "all PVCs Bound in ${NS}" ""
else
  emit ERROR pvc "unbound PVC(s): ${unbound}" "kubectl -n ${NS} describe pvc <name>; check Longhorn pods and node disk"
fi

backup_target=$("$KUBECTL" -n longhorn-system get setting backup-target \
  -o jsonpath='{.value}' 2>/dev/null || true)
if [ -z "$backup_target" ]; then
  emit WARN backup "Longhorn backup target is unset" "single-node Longhorn is one replica; configure a backup target for durability"
else
  emit OK backup "backup target configured" "$backup_target"
fi

# ── platform pieces ──────────────────────────────────────────────────
check_ns_deploy() {
  local ns="$1" label="$2"
  if ! "$KUBECTL" get namespace "$ns" >/dev/null 2>&1; then
    emit ERROR "$label" "namespace ${ns} is missing" "run deploy-models.yml (cert-manager and KServe)"
    return
  fi
  local bad
  bad=$("$KUBECTL" -n "$ns" get pods --no-headers 2>/dev/null \
    | grep -Ev 'Running|Completed' | wc -l | tr -d ' ')
  if [ "$bad" -eq 0 ]; then
    emit OK "$label" "pods healthy in ${ns}" ""
  else
    emit ERROR "$label" "${bad} pod(s) not Running in ${ns}" "kubectl -n ${ns} get pods; describe the failing pod"
  fi
}
check_ns_deploy cert-manager cert-manager
check_ns_deploy kserve kserve
check_ns_deploy longhorn-system longhorn

# ── model pods ───────────────────────────────────────────────────────
bad_pods=$("$KUBECTL" -n "$NS" get pods --no-headers 2>/dev/null \
  | awk '$3 !~ /Running|Completed/ {print $1"("$3")"}' | tr '\n' ' ')
if [ -z "${bad_pods// /}" ]; then
  emit OK pods "all pods Running or Completed in ${NS}" ""
else
  emit ERROR pods "unhealthy: ${bad_pods}" "kubectl -n ${NS} describe pod <name>; kubectl -n ${NS} logs <name>"
fi

for reason in ImagePullBackOff ErrImagePull CrashLoopBackOff OOMKilled; do
  count=$("$KUBECTL" -n "$NS" get pods --no-headers 2>/dev/null | grep -c "$reason" || true)
  if [ "$count" -gt 0 ]; then
    emit ERROR "$reason" "${count} pod(s) show ${reason}" "check the image is published for arm64 and the container limits"
  fi
done

gpu_pods=$("$KUBECTL" -n "$NS" get pods -o jsonpath='{range .items[*]}{.spec.containers[*].resources.requests.nvidia\.com/gpu}{"\n"}{end}' 2>/dev/null \
  | awk '$1 == 1 {n++} END {print n+0}')
if [ "$gpu_pods" -gt "$GPU_SLICES" ]; then
  emit WARN gpu-budget "${gpu_pods} GPU pods requested, ${GPU_SLICES} slices available" "disable a model or raise the time-slicing replica count"
else
  emit OK gpu-budget "${gpu_pods}/${GPU_SLICES} slices requested" ""
fi

# ── named models (passed as args) ────────────────────────────────────
for model in "$@"; do
  dep="${model}-predictor"
  if ! "$KUBECTL" -n "$NS" get deployment "$dep" >/dev/null 2>&1; then
    emit ERROR "model:${model}" "deployment ${dep} does not exist" "make models, or check the model name in the catalog"
    continue
  fi
  ready=$("$KUBECTL" -n "$NS" get deployment "$dep" \
    -o jsonpath='{.status.readyReplicas}' 2>/dev/null || true)
  if [ "${ready:-0}" -ge 1 ]; then
    emit OK "model:${model}" "predictor ready" ""
  else
    emit ERROR "model:${model}" "predictor has no ready replica" "kubectl -n ${NS} logs deploy/${dep} --tail=100"
    continue
  fi
  if "$KUBECTL" -n "$NS" exec "deploy/${dep}" -- ollama list >/dev/null 2>&1; then
    emit OK "register:${model}" "runtime responds to ollama list" ""
  else
    # Not all engines are Ollama; only warn for the ones that are not.
    emit WARN "register:${model}" "ollama list did not answer (non-Ollama engine?)" "check the engine and its logs"
  fi
done

# ── host disk ────────────────────────────────────────────────────────
if command -v df >/dev/null 2>&1; then
  read -r used_pct avail_kb <<<"$(df -Pk / | awk 'NR==2 {print $5, $4}')"
  avail_gib=$((avail_kb / 1048576))
  used_num="${used_pct%\%}"
  if [ "$used_num" -ge 90 ] || [ "$avail_gib" -lt 20 ]; then
    emit ERROR disk "/ at ${used_pct}, ${avail_gib} GiB free" "remove stale model blobs or expand the volume"
  elif [ "$used_num" -ge 80 ]; then
    emit WARN disk "/ at ${used_pct}, ${avail_gib} GiB free" "run the blob garbage collection before the next pull"
  else
    emit OK disk "/ at ${used_pct}, ${avail_gib} GiB free" ""
  fi
fi

echo "SUMMARY	errors=${errors}"
exit "$errors"
