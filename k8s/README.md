# Kubernetes manifests

These YAML files deploy the 0pnMatrx gateway as a single-replica
Deployment with a ConfigMap, Secret, PersistentVolumeClaim, Service, and
optional Ingress.

## Files

| File                   | Purpose                                         |
|------------------------|-------------------------------------------------|
| `namespace.yaml`       | Dedicated `opnmatrx` namespace                  |
| `configmap.yaml`       | Non-secret `openmatrix.config.json`             |
| `secret.example.yaml`  | Template for `opnmatrx-secrets` (do not commit) |
| `pvc.yaml`             | Persistent storage for SQLite + backups         |
| `deployment.yaml`      | Gateway Deployment with health probes           |
| `service.yaml`         | ClusterIP Service on port 80                    |
| `ingress.yaml`         | TLS-terminating Ingress (cert-manager)          |

## Apply order

```bash
kubectl apply -f namespace.yaml
kubectl apply -f configmap.yaml
# Create the Secret from literals (never commit real values):
kubectl -n opnmatrx create secret generic opnmatrx-secrets \
    --from-literal=OPENMATRIX_PAYMASTER_KEY=... \
    --from-literal=ANTHROPIC_API_KEY=... \
    --from-literal=OPENMATRIX_API_KEY=...
kubectl apply -f pvc.yaml
kubectl apply -f deployment.yaml
kubectl apply -f service.yaml
kubectl apply -f ingress.yaml  # optional — only if using cert-manager + nginx
```

## Constraints

- **replicas: 1** — SQLite only supports one writer. Bumping replicas
  will corrupt the database. Switch to a shared DB backend before
  scaling horizontally.
- **Persistent storage required** — the PVC holds the SQLite database,
  daily backups, and the event log. Without it every pod restart loses
  state.
- **Required secrets** — the gateway refuses to start in production
  mode without `OPENMATRIX_PAYMASTER_KEY` in the environment. Other
  provider keys are optional.

## Probes

All three probes (`liveness`, `readiness`, `startup`) hit `/health`,
which is intentionally cheap and auth-free. Startup probe gives the
gateway up to 2 minutes to come up before liveness takes over.

## Resource requests

The default `200m / 512Mi` request / `1 / 2Gi` limit fits a small
deployment. Scale up the CPU request if you're seeing p99 latency climb
under load, and the memory limit if you're running large conversation
histories or multiple LLM providers simultaneously.
