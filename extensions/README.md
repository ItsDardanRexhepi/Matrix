# 0pnMatrx Component Registry

The component registry is the machine-readable manifest of all blockchain
services available on the 0pnMatrx platform. It serves three purposes:

1. **MTRX iOS app** — fetches the registry on launch to discover available
   components and their tier requirements
2. **Web interface** — renders the component grid with real-time availability
3. **Gateway enforcement** — the FeatureGate reads tier requirements to
   gate access at the API level

## Registry Endpoint

```
GET /extensions/registry
```

Returns the full `registry.json` as JSON. No authentication required.

```
GET /extensions/registry/{component_id}
```

Returns a single component entry by ID.

## Adding a New Component

1. Add the service implementation under `runtime/blockchain/services/{service_name}/`
2. Add action entries to `runtime/blockchain/services/service_dispatcher.py`
3. Add a component entry to `extensions/registry.json`:

```json
{
  "id": "your_service",
  "name": "Your Service Name",
  "description": "What it does in one line",
  "category": "finance",
  "min_tier": "free",
  "limits": {
    "free": {"operations_per_month": 5},
    "pro": {"operations_per_month": 100},
    "enterprise": {"operations_per_month": -1}
  },
  "gateway_actions": ["your_action_1", "your_action_2"],
  "icon": "sf.symbol.name",
  "available": true
}
```

4. Validate against `schema.json`
5. Add intent mappings to `runtime/chat/intent_actions.py`

Note: Feature gating (free/pro/enterprise tiers) is enforced client-side
in the MTRX iOS app via StoreKit and Apple IAP. The backend exposes all
extensions uniformly; the app decides which are available per tier.

## Tier Requirements

| Tier | Description |
|------|-------------|
| `free` | Generous limits for personal use |
| `pro` | Higher limits, priority responses, early access |
| `enterprise` | Unlimited usage, team accounts, API access |

Subscription pricing is defined in the MTRX iOS app.

A limit of `-1` means unlimited. Boolean limits (`true`/`false`) indicate
feature availability rather than count-based limits.

## How the MTRX App Uses It

The iOS `ComponentRegistry` class fetches this endpoint on launch:

```swift
func load() async {
    let url = URL(string: "\(gatewayURL)/extensions/registry")!
    let (data, _) = try await URLSession.shared.data(from: url)
    let manifest = try JSONDecoder().decode(ComponentManifest.self, from: data)
    self.components = manifest.components
}
```

Components are filtered by the user's current tier before display.
