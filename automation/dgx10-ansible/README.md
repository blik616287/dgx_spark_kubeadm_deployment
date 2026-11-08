# dgx10-ansible

An Ansible framework that takes a DGX Spark from bare Ubuntu to a serving
Ollama/KServe stack, using
[`blik616287/dgx_spark_kubeadm_deployment`](https://github.com/blik616287/dgx_spark_kubeadm_deployment)
as the deployment definition.

It does not reimplement that repo. It pins a revision, checks it out on the
target, and runs the repo's own playbooks **on the target**, because
`deploy-models.yml` resolves the Helm chart with `playbook_dir` and
`deploy-graphrag.yml` builds from the checkout's `apps/`. Wrapping keeps the
upstream definition authoritative and keeps this framework readable: it adds
gates, ordering, model selection, and verification, not a second copy of the
cluster install.

## Topology

```
 Mac (this repo)                              dgx10
 ┌──────────────────────────┐   zrok tunnel   ┌──────────────────────────────┐
 │ ansible-playbook         │ ──────────────► │ sshd on localhost:22         │
 │  -i inventory/zrok.ini   │ 127.0.0.1:2222  │                              │
 │                          │                 │ ~/dgx-spark  (pinned checkout)│
 │ scripts/tunnel.sh        │                 │   └─ ansible-playbook …      │
 │  zrok access private     │                 │        install-k8s.yml       │
 └──────────────────────────┘                 │        download-models.yml   │
                                              │        deploy-models.yml     │
                                              └──────────────────────────────┘
```

Every wrapped playbook runs on dgx10 with `--become`, so this framework needs
only SSH and the target's own Ansible. The Mac needs `ansible-playbook` and
`zrok`.

## Prerequisites

### On the Mac

```sh
brew install ansible           # or: pipx install ansible-core
zrok version                   # v1.1.13 is what the tunnel was validated with
```

`zrok` must already be enabled in your environment (`zrok enable <token>` once).
The **share token** is a different value, produced on dgx10 by
`zrok reserve private localhost:22 --backend-mode tcpTunnel --json-output`.
An enable token will fail here with `accessNotFound`.

### On dgx10

- DGX Spark (GB10, `aarch64`) on Ubuntu, with the NVIDIA driver and
  `nvidia-ctk` installed — `nvidia-smi -L` and `nvidia-ctk --version` must work.
- Passwordless sudo for the SSH user. The upstream playbooks call `sudo`
  non-interactively and cannot prompt through this framework.
- SSH reachable through the zrok share (Remote Login enabled).
- ~100 GiB free on `/` for the default model PVs, before container images.
- `ansible-playbook` on the target. `dgx_preflight` installs it with apt when
  `dgx_install_ansible: true`.

## Quick start

```sh
cd ~/dgx10-ansible

# 1. Put dgx10's SSH on 127.0.0.1:2222.
scripts/tunnel.sh start "$DGX_SHARE_TOKEN"      # or: make tunnel SHARE_TOKEN=…
scripts/tunnel.sh status

# 2. Prove the connection before touching anything.
make ping

# 3. Preflight + checkout only. Changes nothing on the cluster.
make bootstrap

# 4. The cluster. This is the long step (~20–40 min, image pulls included).
make k8s

# 5. Weights into the PVCs, then the chart.
make models

# 6. Independent evidence: nodes, pods, InferenceService, PVCs, ollama list,
#    and a real chat completion.
make verify
```

`make site` runs steps 3–6 in one pass. Run it in `tmux`/`screen`: the cluster
and model steps take long enough that a dropped SSH session should not be the
thing that kills the run.

### Plan first, then one command

```sh
make plan PROFILE=rag      # fit table only; no SSH, no cluster contact
make up    PROFILE=rag      # bootstrap, cluster if missing, models, gateway, verify
```

`make plan` resolves a profile or an explicit set against the GB10's 120 GiB
usable pool and refuses a set that cannot fit. `make up` probes the cluster
first and skips `install-k8s.yml` when a Ready node exists, so it is safe to
re-run; `dgx_up_force_cluster_install=true` rebuilds anyway.

### Running on the DGX instead of over the tunnel

```sh
make bootstrap INV=inventory/local.ini
make k8s       INV=inventory/local.ini
```

`local.ini` uses `ansible_connection=local`; no tunnel or SSH key is needed.

## Multi-model deployment

Two layers decide what is served.

**The base pair** from the pinned chart (`qwen3-coder-next`,
`deepseek-r1-distill-32b`). `dgx_models_enabled` selects them:

| Value | Meaning |
|---|---|
| `null` (default) | leave the chart defaults alone (both on) |
| `[]` | disable both — serve extras only |
| `[qwen3-coder-next]` | exactly these, the rest off |

```sh
# Serve only the coding model.
make models MODELS='["qwen3-coder-next"]'

# Serve no base models; rely on dgx_extra_models.
make models MODELS='[]'

# Without make — note the JSON form. Ansible does not coerce `-e key=[a]`;
# it arrives as a string and would substring-match model names.
ansible-playbook -i inventory/zrok.ini playbooks/models.yml \
  -e '{"dgx_models_enabled": ["qwen3-coder-next"]}'
```

**Extras** (`dgx_extra_models`): any number of additional Ollama models, each
with its own PVC, pull, checksum verification and InferenceService.

```yaml
# inventory/group_vars/all.yml
dgx_extra_models:
  - name: qwen3-14b
    enabled: true
    source: ollama
    tag: "qwen3:14b"
    size: 20Gi
    numCtx: "32768"
  - name: llama32-3b
    enabled: true
    source: ollama
    tag: "llama3.2:3b"
    size: 5Gi
    numCtx: "8192"
```

`name`, `enabled`, `source` and `tag` are required. Optional per entry:
`displayName`, `storageClass`, `image`, `port`, `numParallel`, `resources`,
`nodePort`, and `chart_values` (merged into the chart entry, e.g.
`toolsAlias`). `source` must be `ollama`: the `llm-serving` chart only runs
Ollama. The upstream HuggingFace model is served by the GraphRAG stack, not by
this chart.

### What `make models` does with a catalog

1. `download-models.yml` pulls the base pair (upstream behaviour).
2. `deploy-models.yml` installs cert-manager and KServe and the initial
   release.
3. `dgx_multimodel` then, for each enabled extra:
   - creates `ollama-<name>` with Helm ownership metadata and
     `helm.sh/resource-policy: keep`;
   - checks for a complete Ollama manifest, pulls the tag when missing or
     partial, and verifies every blob's SHA-256 against the manifest;
4. reads the chart's own `values.yaml`, applies the base enable flags, merges
   the extras, writes `~/.dgx10-ansible/models-values.yml`, and runs one
   `helm upgrade --install --values … --wait`.

The values file is rendered from the chart defaults on every run, so the served
set is exactly what the two variables say. There is no `--reuse-values` drift
from whatever a previous release contained.

Every served model requests `nvidia.com/gpu: 1`, so the count is capped at
`dgx_max_gpu_pods` (5 — the time-slicing replicas `install-k8s.yml` grants).
The role asserts this before pulling anything.

### Adding a model later

```sh
make multimodel
```

Runs the repo role plus `dgx_multimodel` only: pulls and merges the new catalog
without re-running the base download. It assumes the cluster and KServe already
exist (`make models` once).

### Endpoints

KServe RawDeployment gives each model
`http://<name>-predictor.llm-serving.svc.cluster.local:80`. Set `nodePort:` on
an extra entry to also create a `<name>-nodeport` Service selecting that
model's pods.

### Disabling a model

An extra with `enabled: false`, or a base model omitted from
`dgx_models_enabled`, loses its InferenceService. Before the Helm pass that
removes it, every model PVC is annotated `helm.sh/resource-policy: keep`, so
the weights survive and re-enabling does not re-download. Helm honours that
annotation when it prunes resources during an upgrade.

## Profiles, planning and the catalog

`catalog/models.yaml` describes what can be served: weights, KV cache per 1k
tokens, context, capabilities and licence. `catalog/profiles.yaml` holds named
sets that have been planned against the budget.

```sh
make plan                          # the declared set (group_vars)
make plan PROFILE=full             # a profile from profiles.yaml
make plan CATALOG_MODELS='["qwen3-14b","qwen3-8b"]'
```

The planner is a pure function of the catalog: weights + KV at the declared
context × parallel requests + per-model overhead, against
`unified_memory_gib - host_reserve_gib`. Weights are the published quant size
and KV is the model's reported geometry — **estimates, not measurements**.
Replace an entry's numbers once `make verify` has run on that model. The plan
also counts GPU time-slices (5), which cap concurrency independently of memory.

`make models PROFILE=…` and `make verify PROFILE=…` resolve the same selection
before acting. With `dgx_profile` and `dgx_catalog_models` both empty, the
hand-written `dgx_models_enabled` / `dgx_extra_models` selection stays in
charge, so existing runs are unchanged.

## Day-2 toolbox

| Command | What it does | Touches the cluster |
|---|---|---|
| `make plan` | fit table, written to `reports/plan-latest.txt` | no |
| `make up` | full bring-up, cluster only if missing | yes |
| `make model MODEL=qwen3-14b` | add one catalog model to the declared set | yes |
| `make verify` | per-model OpenAI probes → `reports/verify-*.{json,md}` | read only |
| `make doctor` | read-only diagnosis; ERROR findings fail the play | read only |
| `make gateway` | LiteLLM OpenAI-compatible gateway + client recipes | yes |
| `make backup ACTION=snapshot\|backup` | Longhorn Snapshot/Backup of model PVCs; `SCHEDULE="0 3 * * *"` installs a RecurringJob | yes |
| `make restore NAME=<snap-or-backup> [PVC=…]` | restore into a **new** PVC, leaving the source untouched | yes |
| `make observe` | kube-prometheus-stack + DCGM ServiceMonitor + dashboard | yes |
| `make eval` | fixed report card per chat model → `reports/eval-*.{json,md}` | read only |
| `make security` | NetworkPolicies + `reports/NOTICE.md` licence table | yes |
| `make bundle ACTION=create\|verify\|load` | offline images/charts/weights bundle | create: read |
| `make quantize` | experimental GGUF conversion (opt-in twice) | yes |
| `make join` | join every other host in the `dgx` group | yes |
| `make leave` | drain, delete and kubeadm-reset a worker (`dgx_leave_confirm=true`) | yes |
| `make upgrade [REVISION=…]` | `helm upgrade --reuse-values`; rollback to the prior revision on failure | yes |
| `make gitops` | render an Argo CD tree to `reports/gitops/` | no (apply is opt-in) |
| `make argocd` | install Argo CD and register the rendered Application | yes |
| `make power` | tokens/joule and $/1M tokens from the last verify | no |
| `make power-sample` | sample GPU watts on the target and print the spread | read only |

**Gateway.** Set `DGX_GATEWAY_MASTER_KEY` (16+ characters) before
`make gateway`; the role fails closed without it. The service is ClusterIP by
default; set `dgx_gateway_node_port` to expose it on the node. Client recipes
land in `reports/clients/` and read the key from the cluster rather than
writing it to disk. LiteLLM runs without a database here, so spend counters do
not survive a restart.

**Verification.** `make verify` probes every served model, not only the first:
`/v1/models`, a chat completion, and each capability the catalog claims.
Tool calling and structured output are soft checks unless
`dgx_verify_strict_tools` / `dgx_verify_strict_structured` is set. The report
records status, content, time-to-first-token and tokens/second.

**Eval.** `make eval` runs five fixed, checkable cases (exact instruction,
arithmetic, capital, JSON shape, single word). It is a report card, not a
benchmark: a pass says the model can follow a short instruction, not that it
reasons or codes well.

**Security caveat.** The upstream install uses Flannel, which accepts
NetworkPolicy objects and does not enforce them. `make security` detects the
CNI, says so plainly, and records the policies anyway; set
`dgx_security_require_enforcement=true` to make the play fail on a
non-enforcing CNI, or set `dgx_security_install_policy_engine=true` to install
Calico in policy-only mode beside Flannel (routing stays with Flannel, policy
is enforced by Calico). With an enforcing CNI, kubelet readiness probes may
need `dgx_security_probe_cidrs`.

**Gateway TLS and key rotation.** `dgx_gateway_tls=true` requires
`dgx_gateway_host` and `dgx_gateway_cluster_issuer`; the role renders a
cert-manager `Certificate` and an Ingress, then points clients at
`https://<host>/v1`. `make gateway-rotate` generates a new master key, applies
it, restarts LiteLLM and writes the key to `dgx_gateway_key_file` (mode 0600,
outside the repo) — the rendered Secret is deleted after apply.

**Durability.** `make backup SCHEDULE="0 3 * * *"` installs a Longhorn
`RecurringJob` and labels each model volume into its group, so snapshots are
taken without a playbook run. `make restore` never writes into the live PVC: it
creates a new Longhorn volume from the snapshot or backup URL and binds a fresh
PVC to it, then waits for `Bound`.

**GitOps and upgrades.** `make gitops` renders the Application and engine
manifests; `dgx_gitops_pin_digests=true` resolves every tag to `repo@sha256`
and `dgx_gitops_offline=true` omits the weight-fetch init container.
`make argocd` installs the pinned Argo CD release and applies the rendered
Application. `make upgrade` records the current Helm revision, runs
`helm upgrade --reuse-values`, and on failure rolls back to that exact revision
before failing the play.

**Multi-node.** `make join` creates a token and joins every other host;
`make leave` is the supported way out of a cluster — drain (on the control
plane), delete the Node, `kubeadm reset`, and clear the CNI, kubelet and admin
config so the host can rejoin. It refuses to run without
`dgx_leave_confirm=true`.

**Power.** The draw is the mean of `dgx_power_samples` `nvidia-smi` readings,
not a single point sample; `make power-sample` records the same loop to
`reports/power-samples-*.txt` and prints min/max/spread. It is still one load
point, not an energy meter.

**Quantisation.** Off unless `dgx_quantize_confirm=true` *and*
`dgx_quantize_model` *and* `dgx_quantize_pvc` are all set. It downloads a
HuggingFace snapshot, converts to f16, quantises in-cluster, and writes a GGUF
to the PVC. Nothing else in the framework consumes the output.

## Layout

```
ansible.cfg             roles_path + inventory default (run from this directory)
catalog/
  models.yaml           fit data, tags, capabilities, licences
  profiles.yaml         named model sets planned against the budget
lib/
  dgxcatalog.py         planner + resolver (CLI: plan/list/show/profiles/resolve)
  dgxprobe.py           per-model OpenAI probes (models/chat/tools/json/embed/rerank)
  dgxeval.py            fixed report card per chat model
  render_gitops.py       Argo CD Application + non-Ollama engine manifests
  registry.py           image digest pinning + arm64 manifest checks
  power_report.py       tokens/joule and $/1M tokens from a verify report
inventory/
  zrok.ini              dgx10 over 127.0.0.1:2222
  local.ini             dgx10 directly (ansible_connection=local)
  group_vars/all.yml    pins, identity, selection, reports, feature knobs
  host_vars/dgx10.yml   maps dgx_ssh_* onto Ansible connection vars
playbooks/
  plan.yml              fit table only
  up.yml                bootstrap → cluster if missing → models → gateway → verify
  bootstrap.yml         preflight + repo checkout
  k8s.yml               install-k8s.yml
  models.yml            base download + deploy + merged model set
  model.yml             add one catalog model
  multimodel.yml        reconcile extras only (cluster already up)
  verify.yml            per-model probes + JSON/Markdown report
  doctor.yml            read-only diagnosis
  gateway.yml           LiteLLM gateway + client recipes
  backup.yml            Longhorn Snapshot/Backup or a recurring snapshot schedule
  restore.yml           restore a snapshot or backup into a new PVC
  observability.yml     Prometheus + Grafana + GPU dashboard
  eval.yml              model report card
  security.yml          NetworkPolicies + licence notices
  bundle.yml            offline bundle create/verify/load
  quantize.yml          experimental GGUF conversion
  join.yml              join additional nodes
  leave.yml             drain, delete and kubeadm-reset a worker
  upgrade.yml           helm upgrade with rollback to the previous revision
  gitops.yml            render the Argo CD tree
  argocd.yml            install Argo CD and register the rendered Application
  power.yml             power and cost per token
  graphrag.yml          optional GraphRAG stack
  teardown.yml          remove-graphrag → remove-models → remove-k8s
  site.yml              bootstrap → k8s → models → verify
roles/
  dgx_preflight/        asserts, sudo, disk, ansible on the target
  dgx_repo/             pinned checkout + expected-file check
  dgx_plan/             runs the planner, prints and records the fit table
  dgx_catalog/          resolves a profile/model list into role variables
  dgx_cluster/          runs install-k8s.yml
  dgx_models/           runs the base playbooks, then dgx_multimodel
  dgx_multimodel/       extra PVCs/pulls/checksums + merged Helm values
  dgx_engines/          vLLM / llama.cpp / SGLang deployments
  dgx_verify/           kubectl, ollama list, smoke test, per-model probes
  dgx_doctor/           runs scripts/doctor.sh and fails on ERROR
  dgx_gateway/          LiteLLM ConfigMap/Secret/Deployment/Service, optional TLS
  dgx_backup/           Longhorn Snapshot/Backup, recurring job, volume labels
  dgx_restore/          Longhorn Volume + pre-bound PV/PVC from snapshot or backup
  dgx_observability/    kube-prometheus-stack + DCGM ServiceMonitor (discovered)
  dgx_eval/             runs the report card, writes JSON and Markdown
  dgx_security/         NetworkPolicies, CNI detection, optional Calico policies
  dgx_bundle/           runs scripts/bundle.sh on the target
  dgx_quantize/         double-gated experimental quantisation Job
  dgx_join/             kubeadm token create + join
  dgx_leave/            drain, remove and reset a worker
  dgx_upgrade/          helm upgrade with rollback on failure
  dgx_gitops/           render (and optionally apply) the Argo CD tree
  dgx_argocd/           install Argo CD and apply the Application
  dgx_power/            samples nvidia-smi, then runs lib/power_report.py
scripts/
  tunnel.sh             zrok access frontend lifecycle
  doctor.sh             read-only diagnosis (LEVEL/CHECK/DETAIL/FIX)
  bundle.sh             offline images/charts/weights bundle
tests/                  planner unit tests (python -m unittest discover -s tests)
Makefile                the entry points
```

`group_vars` and `host_vars` sit beside the inventory on purpose: Ansible loads
variable files adjacent to the inventory file or the playbook, not from the
project root. Keep them under `inventory/`, and run commands from this
directory so `ansible.cfg` (and `roles_path`) is the one that is read.

## What the wrapped playbooks install

From the pinned upstream revision, in order:

1. **`install-k8s.yml`** — containerd with the NVIDIA runtime, kubeadm/kubelet/
   kubectl 1.34, Flannel (`10.244.0.0/16`), Helm 3, the NVIDIA GPU Operator with
   time-slicing (5 replicas), Longhorn and the `longhorn-models` StorageClass,
   and a GPU test pod.
2. **`download-models.yml`** — namespaces, PVCs, wait for `Bound`, then pull the
   Ollama and HuggingFace weights into them through temporary pods.
3. **`deploy-models.yml`** — cert-manager, KServe v0.16.0 in RawDeployment
   mode, then the `llm-serving` Helm release.

## Configuration

All knobs live in
[`inventory/group_vars/all.yml`](inventory/group_vars/all.yml). The ones worth
knowing:

| Variable | Default | Meaning |
|---|---|---|
| `dgx_repo_ref` | `4a0c971…` | commit the framework was written against |
| `dgx_repo_dir` | `$HOME/dgx-spark` | checkout location on dgx10 |
| `dgx_ssh_port` | `2222` | local tunnel port |
| `dgx_models_enabled` | `null` | `null` = chart defaults, `[]` = no base models, list = exactly those |
| `dgx_extra_models` | `[]` | additional models (name/enabled/source/tag + chart knobs) |
| `dgx_max_gpu_pods` | `5` | time-sliced GPU replicas; caps the served set |
| `dgx_chart_extra_sets` | `[]` | extra non-per-model `--set` values |
| `dgx_smoke_model` | first served model | model used by the smoke test |
| `dgx_show_playbook_output` | `false` | stream child-playbook output on success |
| `dgx_profile` | `""` | profile from `catalog/profiles.yaml`; wins over the hand-written set |
| `dgx_catalog_models` | `[]` | explicit catalog names; wins over the hand-written set |
| `dgx_report_dir` | `reports/` | controller directory for plans, verify/eval JSON+MD, notices |
| `dgx_verify_probe_timeout` | `300` | per-request timeout for the functional probes |
| `dgx_verify_allow_fail` | `false` | record failing probes without stopping |
| `dgx_gateway_enabled` | `true` | deploy the gateway during `make up` |
| `dgx_gateway_node_port` | `0` | `0` = ClusterIP; a port exposes it on the node |
| `dgx_gateway_master_key` | `$DGX_GATEWAY_MASTER_KEY` | required; the role fails closed when empty |
| `dgx_gateway_hostname` | `""` | address clients use; empty → `ansible_host` (loopback over the tunnel) |
| `dgx_gateway_tls` | `false` | render a cert-manager `Certificate` + Ingress for the gateway |
| `dgx_gateway_host` | `""` | public DNS name for the TLS Ingress (required when `dgx_gateway_tls`) |
| `dgx_gateway_cluster_issuer` | `letsencrypt-prod` | cert-manager ClusterIssuer to use |
| `dgx_gateway_rotate` | `false` | replace the master key, restart LiteLLM, save the key 0600 |
| `dgx_gateway_key_file` | `reports/.gateway-master-key` | where a rotated key is written (outside the repo) |
| `dgx_observability_enabled` | `true` | install Prometheus/Grafana during `make observe` |
| `dgx_observability_require_gpu` | `false` | fail when no DCGM exporter is found instead of warning |
| `dgx_observability_scrape_interval` | `15s` | DCGM ServiceMonitor scrape interval |
| `dgx_backup_action` | `snapshot` | `snapshot` (on-cluster) or `backup` (needs a target) |
| `dgx_backup_schedule` | `""` | cron for a Longhorn `RecurringJob`; empty = manual only |
| `dgx_backup_retain` | `5` | snapshots/backups the RecurringJob keeps |
| `dgx_backup_group` | `dgx10-models` | `recurring-job-group` label applied to model volumes |
| `dgx_restore_kind` | `auto` | `auto`, `snapshot` or `backup` |
| `dgx_restore_size` | source PVC | size of the restored PVC |
| `dgx_restore_storage_class` | `longhorn-models` | storage class for the restored volume |
| `dgx_leave_confirm` | `false` | required before `make leave` will reset a host |
| `dgx_leave_drain` | `true` | drain the node before deleting it |
| `dgx_upgrade_revision` | `""` | explicit chart revision for `make upgrade` |
| `dgx_upgrade_rollback_on_failure` | `true` | roll back to the recorded revision on failure |
| `dgx_gitops_pin_digests` | `false` | rewrite every image to `repo@sha256` (needs registry access) |
| `dgx_gitops_offline` | `false` | omit the weight-fetch init container from engine manifests |
| `dgx_argocd_enabled` | `true` | install Argo CD during `make argocd` |
| `dgx_argocd_version` | `v2.13.3` | pinned Argo CD release |
| `dgx_security_install_policy_engine` | `false` | install Calico in policy-only mode beside Flannel |
| `dgx_engines_check_arch` | `true` | refuse engine images with no `linux/arm64` manifest |
| `dgx_quantize_memory_gib` | `60` | memory limit for the quantisation Job |
| `dgx_eval_min_score` | `0.8` | report-card floor; below it the play fails |
| `dgx_security_require_enforcement` | `false` | fail when the CNI ignores NetworkPolicy |
| `dgx_power_watts` | `0` | `0` = sample `nvidia-smi` on the target |
| `dgx_power_samples` | `10` | readings averaged for the draw |
| `dgx_power_sample_interval_ms` | `1000` | `nvidia-smi -lms` interval |

`-e` overrides anything. `inventory/host_vars/dgx10.yml` deliberately
dereferences the `dgx_ssh_*` variables so `-e dgx_ssh_user=…` works without
editing inventory.

### Bumping the upstream revision

`dgx_repo` asserts that the pinned tree still contains the four files this
framework invokes. To move forward:

1. Set `dgx_repo_ref` to the new commit.
2. Run `make bootstrap`.
3. If an assert fires, the upstream layout changed — re-check
   `dgx_inner_inventory`, the playbook names, the chart path
   (`charts/llm-serving`), and the model keys in `dgx_base_models`.

The chart is pinned with the repo, so a model rename upstream breaks
`dgx_models_enabled` loudly rather than deploying something unexpected.

## Teardown

```sh
make teardown
```

Runs `remove-graphrag.yml`, `remove-models.yml`, `remove-k8s.yml` in that order,
skipping any step absent from the pinned revision. This removes the cluster and
the PVCs — the downloaded weights go with them. There is no undo short of
re-running `make site`.

## Troubleshooting

**`make ping` fails after `tunnel.sh start` succeeds.** The tunnel forwards to
`localhost:22` as reserved on dgx10. Check Remote Login there
(`systemsetup -getremotelogin`) and that the reserved share is the one you
passed. `tail -n 20 ~/.cache/dgx10-ansible/tunnel.log`.

**`accessNotFound` from `zrok access private`.** The token is an *enable* token,
not a share token. Get the share token from the `zrok reserve … --json-output`
output on dgx10.

**Preflight says sudo needs a password.** Add a NOPASSWD rule for the SSH user,
or run with `INV=inventory/local.ini` on the DGX. The framework will not
partially install a cluster behind a password prompt.

**`install-k8s.yml` fails partway.** Fix the reported step and re-run
`make k8s`; kubeadm is not idempotent across a half-initialized control plane.
If the failure is during `kubeadm init`, reset on the target
(`sudo kubeadm reset -f`, remove `/etc/cni/net.d`, `/var/lib/etcd`) before
retrying.

**`deploy-models.yml` times out waiting for a model.** Large pulls are slow;
raise `dgx_helm_timeout` and re-run `make models`. Confirm the PVC actually
holds the weights before blaming the chart:
`kubectl -n llm-serving exec deploy/qwen3-coder-next-predictor -- ollama list`.

**`verify` fails the smoke test but pods are Running.** The pod can be up before
the model is loaded. The task retries for ~3 minutes; if it still fails, read the
predictor logs:
`kubectl -n llm-serving logs deploy/qwen3-coder-next-predictor --tail=100`.

## Security notes

- The share token is a credential. Do not commit it; pass it as
  `SHARE_TOKEN=…` or `DGX_SHARE_TOKEN`. The tunnel binds to loopback only.
- `ansible.cfg` disables host-key checking for `127.0.0.1` because the zrok
  frontend's endpoint changes between tunnels and the transport is already
  authenticated by the share token. Do not reuse this config for a public host.
- Everything the framework runs is `--become` on dgx10. Treat the share token as
  root-equivalent on that machine and rotate it if it is exposed.
