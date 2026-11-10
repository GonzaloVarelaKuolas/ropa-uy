# Infrastructure for stage 1 (Azure)

What to create before following "Deploy to AKS" in the README. The names below
are the ones the README uses. Change them if you like, but change them there too.

## What you need

| Resource | Name | Settings that matter | Why |
|---|---|---|---|
| Resource group | `rg-ropa-uy` | Region: `brazilsouth` (closest to Uruguay) or `eastus` (often cheaper) | One place to see and delete everything |
| Container registry (ACR) | `acrropauy<something unique>` | SKU **Basic**, admin user **off** | Stores the scraper image; AKS pulls from it |
| AKS cluster | `aks-ropa-uy` | Pricing tier **Free** (no control-plane fee) · 1 node · size `Standard_B2s` (2 vCPU, 4 GB: the minimum for a system node pool) · managed identity · default networking | Runs PostgreSQL and the scraper |
| Role assignment | — | **AcrPull** on the registry for the cluster's kubelet identity | Lets the nodes pull images without passwords |

Not needed yet: a separate database service (PostgreSQL runs inside the
cluster), a public IP or ingress (nothing is exposed until the web app), and
Container Insights / Log Analytics (it costs money; `kubectl logs` is enough
for now).

The PostgreSQL disk is created automatically: the 1 GiB volume claim in
`deploy/aks/postgres.yaml` uses AKS's default storage class, which makes an
Azure Disk on first start. It is deleted with the cluster.

## Option A: Azure CLI (fastest)

```bash
az group create -n rg-ropa-uy -l brazilsouth
az acr create -g rg-ropa-uy -n <acr> --sku Basic
az aks create -g rg-ropa-uy -n aks-ropa-uy \
  --tier free --node-count 1 --node-vm-size Standard_B2s \
  --attach-acr <acr> --generate-ssh-keys
az aks get-credentials -g rg-ropa-uy -n aks-ropa-uy
kubectl get nodes        # one node, STATUS Ready
```

`--attach-acr` creates the AcrPull role assignment for you.

## Option B: Terraform (better practice, and it's on your CV)

The same four resources with the `azurerm` provider:

- `azurerm_resource_group`
- `azurerm_container_registry`: `sku = "Basic"`, `admin_enabled = false`
- `azurerm_kubernetes_cluster`: `sku_tier = "Free"`, `default_node_pool { node_count = 1, vm_size = "Standard_B2s" }`, `identity { type = "SystemAssigned" }`
- `azurerm_role_assignment`: `role_definition_name = "AcrPull"`, `scope` = the registry's id, `principal_id` = `azurerm_kubernetes_cluster.<name>.kubelet_identity[0].object_id`

Keep it in `infra/` at the repo root, and keep `terraform.tfstate` out of Git.

## Costs

The control plane is free on the Free tier. You pay for the node VM, its OS
disk, the PostgreSQL disk, the registry, and outbound traffic. Check current
prices in the Azure pricing calculator for your region before creating it.
Stop the cluster when you're not using it (`az aks stop`): you pay almost
nothing for the VM while it's stopped, but the disks and registry keep
charging.

## Check it worked

```bash
kubectl get nodes                      # 1 node, Ready
az acr repository list -n <acr>        # after `az acr build`: ropa-uy-scraper
kubectl get storageclass               # one marked (default)
```
