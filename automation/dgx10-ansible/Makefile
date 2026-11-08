SHELL   := /bin/sh
# Prefer the project venv (`make deps` creates it). The defaults are here so a
# fresh checkout either works or says exactly what is missing, rather than
# failing with "No module named 'yaml'" halfway through a run.
VENV    ?= .venv
ANSIBLE ?= $(if $(wildcard $(VENV)/bin/ansible-playbook),$(VENV)/bin/ansible-playbook,ansible-playbook)
PYTHON  ?= $(if $(wildcard $(VENV)/bin/python),$(VENV)/bin/python,python3)
INV     ?= inventory/zrok.ini
EXTRA   ?=
# Base-model selection as JSON, e.g. MODELS='["qwen3-coder-next"]' or MODELS='[]'
MODELS  ?=
# Catalog profile, e.g. PROFILE=rag. Takes precedence over MODELS.
PROFILE ?=
# Explicit catalog names as JSON, e.g. CATALOG_MODELS='["qwen3-14b","qwen3-8b"]'
CATALOG_MODELS ?=
# One catalog name, for `make model MODEL=...`
MODEL   ?=
# Action for targets that take one (backup, bundle)
ACTION  ?=
MODEL_ARGS = $(if $(MODELS),-e '{"dgx_models_enabled": $(MODELS)}')
SEL_ARGS   = $(if $(PROFILE),-e '{"dgx_profile": "$(PROFILE)"}') \
             $(if $(CATALOG_MODELS),-e '{"dgx_catalog_models": $(CATALOG_MODELS)}')

.PHONY: help deps check-deps ping tunnel tunnel-stop tunnel-status bootstrap k8s plan up models \
        model multimodel verify doctor gateway gateway-rotate acceptance restore argocd upgrade \
        leave backup observe eval security bundle quantize join gitops power power-sample \
        graphrag site teardown test syntax

help:
	@printf '%s\n' \
	  'make deps           create .venv and install requirements-dev.txt' \
	  'make check-deps     verify the interpreter and ansible-playbook are usable' \
	  'make ping           probe SSH to dgx10 over the tunnel' \
	  'make tunnel         open the zrok tunnel (SHARE_TOKEN=<token>)' \
	  'make tunnel-stop    close the tunnel' \
	  'make tunnel-status  report tunnel state' \
	  'make plan           fit the selected set against the GB10 budget (no cluster contact)' \
	  'make up             one command: bootstrap, cluster if missing, models, gateway, verify' \
	  'make bootstrap      preflight + install ansible + check out the repo' \
	  'make k8s            run install-k8s.yml on dgx10 (slow: ~20-40 min)' \
	  'make models         pull and serve the selected models' \
	  'make model          add one model: MODEL=qwen3-14b' \
	  'make multimodel     add/remove extra models without the base download' \
	  'make verify         nodes/pods/InferenceService + per-model probes + report' \
	  'make acceptance     the live acceptance run: cluster, models, probes, doctor, eval' \
	  'make doctor         read-only diagnosis; ERROR findings fail the play' \
	  'make gateway        install the OpenAI-compatible gateway (needs DGX_GATEWAY_MASTER_KEY)' \
	  'make gateway-rotate replace the gateway master key and restart it' \
	  'make backup         Longhorn snapshot (ACTION=snapshot), backup (ACTION=backup), or SCHEDULE="0 3 * * *"' \
	  'make restore        restore a backup/snapshot into a new PVC (NAME=<snapshot-or-backup>)' \
	  'make leave          reset a worker and remove it from the cluster' \
	  'make upgrade        helm upgrade the serving stack, rollback on failure (REVISION=...)' \
	  'make argocd         install Argo CD and register the rendered application' \
	  'make observe        Prometheus + Grafana + GPU dashboard' \
	  'make eval           fixed report card per chat model' \
	  'make security       NetworkPolicies + licence notices' \
	  'make bundle         offline bundle: ACTION=create|verify|load' \
	  'make quantize       experimental in-cluster GGUF quantisation (opt-in twice)' \
	  'make join           join every host in the dgx group to the control plane' \
	  'make gitops         render the Argo CD tree for review' \
	  'make power          tokens per joule and $/1M tokens from the last verify' \
	  'make power-sample   measure idle and loaded GPU watts on the target' \
	  'make graphrag       optional GraphRAG stack' \
	  'make site           bootstrap + k8s + models + verify' \
	  'make teardown       remove GraphRAG, models, then the cluster' \
	  'make test           run the unit tests (planner, renderers, templates)' \
	  'make syntax         syntax-check every playbook without touching dgx10' \
	  '' \
	  'Overrides: INV=inventory/local.ini  PROFILE=rag  MODELS=["qwen3-coder-next"]' \
	  '           CATALOG_MODELS=["qwen3-14b"]  MODEL=qwen3-14b  ACTION=backup  EXTRA="-e key=value"'

deps:
	python3 -m venv $(VENV)
	$(VENV)/bin/python -m pip install --upgrade pip
	$(VENV)/bin/python -m pip install -r requirements-dev.txt
	@echo "ready: $(VENV)/bin/python and $(VENV)/bin/ansible-playbook"

check-deps:
	@$(PYTHON) -c 'import yaml' 2>/dev/null || { \
	  echo "error: $(PYTHON) cannot import yaml" >&2; \
	  echo "       run 'make deps' (or PYTHON=/path/to/python make $@)" >&2; exit 1; }
	@command -v $(ANSIBLE) >/dev/null 2>&1 || { \
	  echo "error: $(ANSIBLE) not found" >&2; \
	  echo "       run 'make deps' (or ANSIBLE=/path/to/ansible-playbook make $@)" >&2; exit 1; }

ping:
	$(ANSIBLE) -i $(INV) dgx -m ping $(EXTRA)

tunnel:
	@scripts/tunnel.sh start "$(SHARE_TOKEN)"

tunnel-stop:
	@scripts/tunnel.sh stop

tunnel-status:
	@scripts/tunnel.sh status

plan:
	$(ANSIBLE) -i $(INV) playbooks/plan.yml $(SEL_ARGS) $(EXTRA)

up:
	$(ANSIBLE) -i $(INV) playbooks/up.yml $(SEL_ARGS) $(EXTRA)

bootstrap:
	$(ANSIBLE) -i $(INV) playbooks/bootstrap.yml $(EXTRA)

k8s:
	$(ANSIBLE) -i $(INV) playbooks/k8s.yml $(EXTRA)

models:
	$(ANSIBLE) -i $(INV) playbooks/models.yml $(MODEL_ARGS) $(SEL_ARGS) $(EXTRA)

model:
	$(ANSIBLE) -i $(INV) playbooks/model.yml -e 'dgx_model_add=$(MODEL)' $(EXTRA)

verify:
	$(ANSIBLE) -i $(INV) playbooks/verify.yml $(MODEL_ARGS) $(SEL_ARGS) $(EXTRA)

acceptance:
	$(ANSIBLE) -i $(INV) playbooks/acceptance.yml $(MODEL_ARGS) $(SEL_ARGS) $(EXTRA)

doctor:
	$(ANSIBLE) -i $(INV) playbooks/doctor.yml $(MODEL_ARGS) $(SEL_ARGS) $(EXTRA)

gateway:
	$(ANSIBLE) -i $(INV) playbooks/gateway.yml $(SEL_ARGS) $(EXTRA)

gateway-rotate:
	$(ANSIBLE) -i $(INV) playbooks/gateway.yml -e dgx_gateway_rotate=true $(SEL_ARGS) $(EXTRA)

backup:
	$(ANSIBLE) -i $(INV) playbooks/backup.yml \
	  -e 'dgx_backup_action=$(if $(ACTION),$(ACTION),snapshot)' \
	  $(if $(SCHEDULE),-e 'dgx_backup_schedule=$(SCHEDULE)',) $(EXTRA)

restore:
	@test -n "$(NAME)" || { echo "usage: make restore NAME=<snapshot-or-backup> [PVC=...] [KIND=...]" >&2; exit 2; }
	$(ANSIBLE) -i $(INV) playbooks/restore.yml -e 'dgx_restore_name=$(NAME)' \
	  $(if $(PVC),-e 'dgx_restore_pvc=$(PVC)',) \
	  $(if $(KIND),-e 'dgx_restore_kind=$(KIND)',) $(EXTRA)

leave:
	$(ANSIBLE) -i $(INV) playbooks/leave.yml $(EXTRA)

upgrade:
	$(ANSIBLE) -i $(INV) playbooks/upgrade.yml \
	  $(if $(REVISION),-e 'dgx_upgrade_revision=$(REVISION)',) $(SEL_ARGS) $(EXTRA)

argocd:
	$(ANSIBLE) -i $(INV) playbooks/argocd.yml $(SEL_ARGS) $(EXTRA)

observe:
	$(ANSIBLE) -i $(INV) playbooks/observability.yml $(EXTRA)

eval:
	$(ANSIBLE) -i $(INV) playbooks/eval.yml $(MODEL_ARGS) $(SEL_ARGS) $(EXTRA)

security:
	$(ANSIBLE) -i $(INV) playbooks/security.yml $(MODEL_ARGS) $(SEL_ARGS) $(EXTRA)

bundle:
	$(ANSIBLE) -i $(INV) playbooks/bundle.yml -e 'dgx_bundle_action=$(if $(ACTION),$(ACTION),create)' $(EXTRA)

quantize:
	$(ANSIBLE) -i $(INV) playbooks/quantize.yml $(EXTRA)

join:
	$(ANSIBLE) -i $(INV) playbooks/join.yml $(EXTRA)

gitops:
	$(ANSIBLE) -i $(INV) playbooks/gitops.yml $(MODEL_ARGS) $(SEL_ARGS) $(EXTRA)

power:
	$(ANSIBLE) -i $(INV) playbooks/power.yml $(EXTRA)

power-sample:
	$(ANSIBLE) -i $(INV) playbooks/power.yml -e dgx_power_sample=true $(EXTRA)

multimodel:
	$(ANSIBLE) -i $(INV) playbooks/multimodel.yml $(MODEL_ARGS) $(SEL_ARGS) $(EXTRA)

graphrag:
	$(ANSIBLE) -i $(INV) playbooks/graphrag.yml $(EXTRA)

site:
	$(ANSIBLE) -i $(INV) playbooks/site.yml $(MODEL_ARGS) $(SEL_ARGS) $(EXTRA)

teardown:
	$(ANSIBLE) -i $(INV) playbooks/teardown.yml $(EXTRA)

test: check-deps
	cd $(CURDIR) && $(PYTHON) -m unittest discover -s tests

syntax: check-deps
	@set -e; for p in $(wildcard playbooks/*.yml); do \
	  printf '%-32s' "$$p"; \
	  $(ANSIBLE) -i $(INV) --syntax-check "$$p" >/dev/null && echo ok; \
	done
