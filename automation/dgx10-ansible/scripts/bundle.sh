#!/usr/bin/env bash
# Offline bundle: container images, Helm charts and model PVC contents in one
# directory with a sha256 manifest. Designed for a network-isolated site: build
# it on a connected DGX, carry it in, then `load` it before the install.
#
#   bundle.sh create OUT_DIR
#   bundle.sh verify BUNDLE_DIR
#   bundle.sh load   BUNDLE_DIR
#
# Environment:
#   KUBECONFIG   cluster access (default: $HOME/.kube/config)
#   DGX_NAMESPACE  model namespace (default: llm-serving)
#   DGX_IMAGES   space-separated image refs; defaults below
#   DGX_PVCS     space-separated PVC names to export; empty = discover
#   DGX_CHARTS   space-separated local chart directories
set -euo pipefail

KUBECTL="${KUBECTL:-kubectl}"
NERDCTL="${NERDCTL:-nerdctl}"
NS="${DGX_NAMESPACE:-llm-serving}"
IMAGES="${DGX_IMAGES:-ollama/ollama:latest busybox:latest python:3.12-slim vllm/vllm-openai:latest ghcr.io/berriai/litellm:main-stable}"
CHARTS="${DGX_CHARTS:-}"

die() { echo "bundle: $*" >&2; exit 1; }

slug() { printf '%s' "$1" | tr '/:@' '____'; }

discover_pvcs() {
  if [ -n "${DGX_PVCS:-}" ]; then
    printf '%s\n' "$DGX_PVCS"
  else
    "$KUBECTL" -n "$NS" get pvc --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null \
      | grep '^ollama-' || true
  fi
}

save_image() {
  local image="$1" out="$2"
  if "$NERDCTL" -n k8s.io images inspect "$image" >/dev/null 2>&1; then
    "$NERDCTL" -n k8s.io save -o "$out" "$image"
  elif command -v ctr >/dev/null 2>&1; then
    ctr -n k8s.io images export "$out" "$image"
  else
    die "neither nerdctl nor ctr can export $image"
  fi
}

load_image() {
  local tar="$1"
  if command -v "$NERDCTL" >/dev/null 2>&1; then
    "$NERDCTL" -n k8s.io load -i "$tar"
  else
    ctr -n k8s.io images import "$tar"
  fi
}

pvc_overrides() {
  local pvc="$1"
  printf '{"spec":{"volumes":[{"name":"data","persistentVolumeClaim":{"claimName":"%s"}}],"containers":[{"name":"bundle","image":"busybox:latest","command":["sh","-c","sleep 3600"],"volumeMounts":[{"name":"data","mountPath":"/data"}]}]}}' "$pvc"
}

cmd_create() {
  local out="$1"
  [ -d "$out" ] && [ -n "$(ls -A "$out" 2>/dev/null || true)" ] && die "$out is not empty"
  mkdir -p "$out"/{images,charts,weights}

  echo "==> images"
  for image in $IMAGES; do
    echo "    $image"
    save_image "$image" "$out/images/$(slug "$image").tar"
  done

  echo "==> charts"
  for chart in $CHARTS; do
    [ -d "$chart" ] || die "chart directory not found: $chart"
    helm package "$chart" -d "$out/charts" >/dev/null
    echo "    $chart"
  done

  echo "==> weights"
  local pvcs
  pvcs="$(discover_pvcs)"
  if [ -z "$pvcs" ]; then
    echo "    (no PVCs found in $NS)"
  fi
  for pvc in $pvcs; do
    echo "    $pvc"
    "$KUBECTL" -n "$NS" run "bundle-export-${pvc}" --rm -i --restart=Never \
      --image=busybox:latest \
      --overrides="$(pvc_overrides "$pvc")" \
      -- tar -C /data -cf - . >"$out/weights/${pvc}.tar"
  done

  echo "==> manifest"
  ( cd "$out" && find . -type f ! -name SHA256SUMS ! -name manifest.json \
      -exec sha256sum {} + | sort -k2 >SHA256SUMS )
  cat >"$out/manifest.json" <<EOF
{
  "created": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "namespace": "${NS}",
  "images": "$(printf '%s' "$IMAGES" | tr ' ' '\n' | wc -l | tr -d ' ')",
  "pvcs": "$(printf '%s' "$pvcs" | tr ' ' '\n' | grep -c . || true)"
}
EOF
  echo "bundle written to $out"
  echo "carry it in, then: bundle.sh verify $out && bundle.sh load $out"
}

cmd_verify() {
  local dir="$1"
  [ -f "$dir/SHA256SUMS" ] || die "$dir has no SHA256SUMS"
  ( cd "$dir" && sha256sum -c SHA256SUMS )
}

cmd_load() {
  local dir="$1"
  cmd_verify "$dir"
  echo "==> images"
  for tar in "$dir"/images/*.tar; do
    echo "    $(basename "$tar")"
    load_image "$tar"
  done
  echo "==> charts"
  for chart in "$dir"/charts/*.tgz; do
    echo "    $(basename "$chart")  (install with: helm upgrade --install <release> $chart)"
  done
  echo "==> weights"
  for tar in "$dir"/weights/*.tar; do
    pvc="$(basename "$tar" .tar)"
    echo "    $pvc"
    "$KUBECTL" -n "$NS" run "bundle-import-${pvc}" --rm -i --restart=Never \
      --image=busybox:latest \
      --overrides="$(pvc_overrides "$pvc")" \
      -- tar -C /data -xf - <"$tar"
  done
  echo "bundle loaded"
}

case "${1:-}" in
  create) shift; [ $# -eq 1 ] || die "usage: bundle.sh create OUT_DIR"; cmd_create "$1" ;;
  verify) shift; [ $# -eq 1 ] || die "usage: bundle.sh verify BUNDLE_DIR"; cmd_verify "$1" ;;
  load)   shift; [ $# -eq 1 ] || die "usage: bundle.sh load BUNDLE_DIR"; cmd_load "$1" ;;
  *) echo "usage: bundle.sh {create OUT_DIR|verify BUNDLE_DIR|load BUNDLE_DIR}" >&2; exit 2 ;;
esac
