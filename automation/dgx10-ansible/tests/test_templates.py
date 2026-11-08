"""Render every role template with representative variables.

Ansible's own templar is used, so the Ansible-only filters (``dict2items``,
``to_nice_json``) behave exactly as they do in a run. YAML templates are parsed
after rendering, which catches the class of bug that only appears on the
target: a manifest the API server would reject.

Templates that are not listed in ``VARIABLES`` fail the suite, so adding a
template means adding its fixture.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

ROOT = Path(__file__).resolve().parents[1]
ROLES = ROOT / "roles"

CATALOG = {
    "qwen3-8b": {
        "display_name": "Qwen3 8B",
        "engine": "ollama",
        "tag": "qwen3:8b",
        "port": 11434,
        "capabilities": ["chat", "tools"],
        "license": "Apache-2.0",
    },
    "qwen3-embedding-0.6b": {
        "display_name": "Qwen3 Embedding 0.6B",
        "engine": "ollama",
        "tag": "qwen3-embedding:0.6b",
        "port": 11434,
        "capabilities": ["embedding"],
        "license": "Apache-2.0",
    },
    "bge-reranker-v2-m3": {
        "display_name": "BGE Reranker v2 M3",
        "engine": "vllm",
        "tag": "BAAI/bge-reranker-v2-m3",
        "port": 8000,
        "capabilities": ["rerank"],
        "license": "Apache-2.0",
    },
}

VARIABLES = {
    "ansible_date_time": {"iso8601": "2026-11-07T00:00:00Z"},
    "dgx_catalog_meta": CATALOG,
    "dgx_served_models": list(CATALOG),
    "dgx_models_namespace": "llm-serving",
    "dgx_gateway_namespace": "dgx-gateway",
    "dgx_gateway_image": "ghcr.io/berriai/litellm:main-stable",
    "dgx_gateway_port": 4000,
    "dgx_gateway_node_port": 0,
    "dgx_gateway_master_key": "0123456789abcdef",
    "dgx_gateway_endpoint": "http://127.0.0.1:4000/v1",
    "dgx_gateway_tls": False,
    "dgx_gateway_ingress_class": "nginx",
    "dgx_gateway_cluster_issuer": "ca-issuer",
    "dgx_gateway_host": "",
    "dgx_grafana_password": "generated-password",
    "dgx_observability_namespace": "monitoring",
    "dgx_observability_retention": "7d",
    "dgx_quantize_namespace": "llm-serving",
    "dgx_quantize_model": "Qwen/Qwen3-8B",
    "dgx_quantize_pvc": "ollama-model",
    "dgx_quantize_outtype": "q4_k_m",
    "dgx_quantize_image": "ghcr.io/ggerganov/llama.cpp:full",
    "dgx_quantize_deadline": 14400,
    "dgx_quantize_memory_gib": 60,
    "dgx_security_allow_namespaces": ["llm-serving", "dgx-gateway"],
    "dgx_security_model_ports": [11434, 8000],
    "dgx_security_probe_cidrs": ["10.0.0.0/8"],
    "dgx_security_allow_egress_443": True,
    "dgx_security_enforced": True,
    "dgx_security_cni": "calico",
    "dgx_gateway_tls_decoy": None,
    "dgx_backup_action": "snapshot",
    "dgx_backup_name": "dgx10-test",
    "dgx_backup_schedule": "0 3 * * *",
    "dgx_backup_retain": 5,
    "dgx_backup_group": "dgx10-models",
    "dgx_backup_recurring_name": "dgx10-model-volumes",
    "dgx_backup_schedule_type": "snapshot",
    "dgx_restore_pvc": "ollama-restored",
    "dgx_restore_name": "dgx10-test-ollama-qwen3-8b",
    "dgx_restore_kind": "snapshot",
    "dgx_restore_size": "60Gi",
    "dgx_restore_size_resolved": "60Gi",
    "dgx_restore_size_bytes": 64424509440,
    "dgx_restore_access_modes": ["ReadWriteOnce"],
    "dgx_restore_storage_class": "longhorn-models",
    "dgx_restore_source_volume": "pvc-1234",
    "dgx_restore_snapshot_name": "dgx10-test-ollama-qwen3-8b",
    "dgx_restore_backup_url": "",
    "dgx_gateway_tls_secret": "litellm-tls",
    "dgx_observability_release": "kube-prometheus-stack",
    "dgx_observability_dcgm_namespace": "gpu-operator",
    "dgx_observability_dcgm_port": "gpu-metrics",
    "dgx_observability_dcgm_target_port": 9400,
    "dgx_observability_scrape_interval": "15s",
    # report contexts
    "stamp": "20261107T000000",
    "models": list(CATALOG),
    "floor": 0.8,
    "dgx_eval_allow_fail": False,
    "dgx_verify_probe": True,
    "plan": {
        "verdict": "PASS",
        "used_gib": 13.57,
        "budget_gib": 120.0,
        "slices_used": 3,
        "slices_max": 5,
        "reasons": [],
    },
    "probes": [
        {
            "model": "qwen3-8b",
            "ok": True,
            "checks": [{"name": "chat", "ok": True, "soft": False, "detail": {"status": 200}}],
            "metrics": {"tokens_per_s": 41.2, "warm_s": 0.9},
        }
    ],
    "reports": [
        {
            "model": "qwen3-8b",
            "score": 1.0,
            "passed": 5,
            "total": 5,
            "elapsed_s": 4.2,
            "cases": [{"name": "exact_instruction", "ok": True, "content": "DGX10-OK"}],
        }
    ],
    # The acceptance report takes one object via the task's vars.
    "result": {
        "stamp": "20261107T000000",
        "models": list(CATALOG),
        "cluster": {
            "nodes_ready": 1,
            "nodes_total": 1,
            "node_names": ["dgx10"],
            "pods_total": 3,
            "pods_not_running": 0,
        },
        "missing_storage_classes": [],
        "plan": {"verdict": "PASS", "used_gib": 13.57, "budget_gib": 120.0,
                 "slices_used": 3, "slices_max": 5},
        "probes": [{"model": "qwen3-8b", "ok": True, "checks": []}],
        "doctor": [{"level": "OK", "check": "nodes", "detail": "1 Ready"}],
        "eval": [{"model": "qwen3-8b", "score": 1.0, "passed": 5, "total": 5}],
        "gateway": {"deployed": True, "attempted": True, "ok": True,
                    "models": ["qwen3-8b"]},
        "checks": {"cluster_reachable": True, "all_nodes_ready": True},
        "ok": True,
    },
}

# Templates whose output is not YAML. They are checked for unresolved Jinja
# and for a non-empty body instead of being parsed.
NON_YAML = {
    "report.md.j2",
    "README.md.j2",
    "NOTICE.md.j2",
    "client.env.j2",
    "curl_example.sh.j2",
    "python_example.py.j2",
}


def render(text: str) -> str:
    templar = Templar(loader=DataLoader(), variables=dict(VARIABLES))
    return templar.template(text, convert_data=False)


def templates() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for role in sorted(ROLES.iterdir()):
        directory = role / "templates"
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.j2")):
            found[f"{role.name}/{path.name}"] = path
    return found


class TemplateTests(unittest.TestCase):
    def test_every_template_variable_has_a_fixture(self) -> None:
        pattern = re.compile(r"\bdgx_[a-z0-9_]+\b")
        undefined = {}
        for name, path in templates().items():
            missing = sorted(
                v for v in set(pattern.findall(path.read_text())) if v not in VARIABLES
            )
            if missing:
                undefined[name] = missing
        self.assertFalse(undefined, f"templates use variables with no fixture value: {undefined}")

    def test_every_template_renders(self) -> None:
        for name, path in templates().items():
            with self.subTest(template=name):
                output = render(path.read_text())
                self.assertTrue(output.strip(), f"{name} rendered empty")
                if path.name != "dashboard.yaml.j2":
                    # The dashboard deliberately emits Grafana's own
                    # ``{{label}}`` legend syntax, which is not Jinja.
                    self.assertNotIn("{{", output, f"{name} left an unresolved expression")
                    self.assertNotIn("{%", output, f"{name} left an unresolved statement")
                if path.name in NON_YAML:
                    continue
                documents = [d for d in yaml.safe_load_all(output) if d is not None]
                self.assertTrue(documents, f"{name} rendered no YAML documents")

    def test_gateway_config_routes_every_served_model(self) -> None:
        output = render((ROLES / "dgx_gateway" / "templates" / "litellm-config.yaml.j2").read_text())
        config = next(d for d in yaml.safe_load_all(output) if d["kind"] == "ConfigMap")
        body = yaml.safe_load(config["data"]["config.yaml"])
        names = [entry["model_name"] for entry in body["model_list"]]
        self.assertEqual(names, list(CATALOG))
        embedding = next(e for e in body["model_list"] if e["model_name"] == "qwen3-embedding-0.6b")
        self.assertEqual(embedding["model_info"]["mode"], "embedding")
        reranker = next(e for e in body["model_list"] if e["model_name"] == "bge-reranker-v2-m3")
        self.assertNotIn("-predictor", reranker["litellm_params"]["api_base"])

    def test_dashboard_declares_its_datasource_variable(self) -> None:
        output = render((ROLES / "dgx_observability" / "templates" / "dashboard.yaml.j2").read_text())
        config_map = yaml.safe_load(output)
        dashboard = json.loads(config_map["data"]["dgx10-overview.json"])
        variables = {item["name"] for item in dashboard["templating"]["list"]}
        self.assertIn("DS_PROMETHEUS", variables)

    def test_network_policies_deny_then_allow(self) -> None:
        output = render((ROLES / "dgx_security" / "templates" / "networkpolicies.yaml.j2").read_text())
        policies = [d for d in yaml.safe_load_all(output) if d]
        names = {p["metadata"]["name"] for p in policies}
        self.assertIn("default-deny-ingress", names)
        self.assertIn("allow-model-ingress", names)
        deny = [p for p in policies if p["metadata"]["name"] == "default-deny-ingress"]
        self.assertEqual(len(deny), 2)


if __name__ == "__main__":
    unittest.main()
