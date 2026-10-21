# Load user overrides if present (see .env.example)
-include .env

# Export variables so scripts and Ansible can access them.
# Only export non-empty values to avoid Ansible interpreting empty paths.
export SSH_PUBKEY_FILE
export VM_CPUS
export VM_MEMORY
export INCUS_IMAGE
export BOOTSTRAP_USER
ifneq ($(strip $(ANSIBLE_PRIVATE_KEY_FILE)),)
export ANSIBLE_PRIVATE_KEY_FILE
endif

# --- Environment selection ---
#
# Every environment lives under configs/<ENV>/ and ships:
#   inventory/   Ansible inventory (hosts.yml, group_vars/, host_vars/)
#   stacks/      Docker Compose stacks (consumed by compose_deploy role)
#   dotfiles/    Files synced to admin user (consumed by admin_dotfiles role)
#   .vault_pass  Ansible Vault password (mode 600, gitignored)
#
# Defaults to `prod`; override with `make <target> ENV=prod2` etc.
ENV ?= prod
LIMIT ?=
LIMIT_FLAG = $(if $(strip $(LIMIT)),--limit $(LIMIT),)
ENV_DIR = configs/$(ENV)
INVENTORY = $(ENV_DIR)/inventory
VAULT_FILE ?= $(INVENTORY)/group_vars/all/vault.yml

# Exported so roles that need to know which env they're running against
# (e.g. local_ssh_config writes per-env files) can read it without
# relying on Ansible magic vars that aren't always set on localhost plays.
export HSP_ENV = $(ENV)

# Always point Ansible at the per-env vault password file. The file may not
# exist yet (e.g. before `make vault-init`); commands that need it will fail
# loudly with a clear ansible-vault error in that case.
export ANSIBLE_VAULT_PASSWORD_FILE = $(ENV_DIR)/.vault_pass

# Extra flags injected by targets (e.g. test-bootstrap clears -kK).
BOOTSTRAP_FLAGS ?= -kK
WG_KEYS_FLAGS ?=

# --- Ansible ---

.PHONY: bootstrap provision wireguard-keys wireguard-render notify-test

bootstrap: ## First run on fresh hosts (ENV=prod by default)
	ansible-playbook playbooks/bootstrap.yml -i $(INVENTORY) -e 'ansible_user={{ bootstrap_user }}' $(BOOTSTRAP_FLAGS) $(LIMIT_FLAG)

provision: wireguard-keys ## Run full site playbook (ENV=prod by default)
	ansible-playbook playbooks/site.yml -i $(INVENTORY) $(LIMIT_FLAG)

wireguard-keys: ## Generate/prune WireGuard client keys (vaulted, auto-committed)
	scripts/wg-ensure-keys.py --inventory $(INVENTORY) $(WG_KEYS_FLAGS)

wireguard-render: ## Render build/$(ENV)/wireguard/<client>.{conf,png} for distribution (sensitive!)
	ansible-playbook playbooks/wireguard_clients.yml -i $(INVENTORY)

notify-test: ## Send a hsp-notify smoke test from HOST=<host> (defaults to all servers)
	@host="$${HOST:-servers}"; \
	echo "Sending hsp-notify smoke test from $$host (ENV=$(ENV))..."; \
	ansible "$$host" -i $(INVENTORY) -b -m shell \
		-a 'hsp-notify --priority default --tags hsp,smoke-test \
			"hsp-notify smoke test from {{ inventory_hostname }}" \
			"Triggered by make notify-test on $$(date -Is). If you see this on your phone, the notifications role is wired up correctly."'

# --- Vault (secrets) ---

.PHONY: vault-init vault-edit vault-view vault-rekey vault-encrypt vault-decrypt

vault-init: ## Create $(ENV_DIR)/.vault_pass (prompts for password, chmod 600)
	@target="$(ENV_DIR)/.vault_pass"; \
	if [ -e "$$target" ] && [ ! -L "$$target" ]; then \
		echo "$$target already exists; refusing to overwrite."; exit 1; \
	fi; \
	mkdir -p "$$(dirname $$target)"; \
	stty -echo; printf "New vault password for ENV=$(ENV): "; read pw; stty echo; echo; \
	printf "%s" "$$pw" > "$$target"; \
	chmod 600 "$$target"; \
	echo "Wrote $$target (mode 600, gitignored)."

vault-edit: ## Edit (and encrypt on first save) $(VAULT_FILE)
	ansible-vault edit $(VAULT_FILE)

vault-view: ## View $(VAULT_FILE) without decrypting to disk
	ansible-vault view $(VAULT_FILE)

vault-encrypt: ## Encrypt a plain-text vault file in place (one-time)
	ansible-vault encrypt $(VAULT_FILE)

vault-decrypt: ## Decrypt $(VAULT_FILE) to plain text in place (DANGEROUS)
	ansible-vault decrypt $(VAULT_FILE)

vault-rekey: ## Re-encrypt $(VAULT_FILE) with a new password
	ansible-vault rekey $(VAULT_FILE)

# --- Test environment ---
#
# Test env is just ENV=test with a pre-built configs/test/ tree that is
# regenerated from scratch by scripts/test-env.sh (gitignored).

.PHONY: test-env-create test-env-destroy test-env-status test-bootstrap test-provision test-wireguard-render test-smoke test-reboot

test-env-create: ## Create test VMs and seed configs/test/
	./scripts/test-env.sh create

test-env-destroy: ## Destroy all test VMs and remove configs/test/
	./scripts/test-env.sh destroy

test-env-status: ## Show test VM status
	./scripts/test-env.sh status

test-bootstrap: ## bootstrap against ENV=test (no password prompt)
	$(MAKE) bootstrap ENV=test BOOTSTRAP_FLAGS=

test-provision: ## provision against ENV=test (no git auto-commit for vault)
	$(MAKE) provision ENV=test WG_KEYS_FLAGS=--no-commit

test-wireguard-render: ## render WG client artifacts for ENV=test
	$(MAKE) wireguard-render ENV=test

test-smoke: ## end-to-end smoke test from the controller via WG (needs sudo)
	@./scripts/test-smoke.sh

test-reboot: ## reboot every test VM and verify services persist across reboots
	@./scripts/test-reboot-check.sh

# --- Setup ---

.PHONY: setup init-config lint

setup: ## Install Ansible, ansible-lint, and required collections
	@./scripts/setup.sh

init-config: ## Create configs/$(ENV)/ from configs/example/ (own git repo)
	@./scripts/init-config.sh "$(ENV)"

lint: ## Run ansible-lint over the repository
	@# Linting needs no vault secrets; a missing vault password file makes
	@# ansible-lint's internal --syntax-check calls fail hard, so drop it.
	@env -u ANSIBLE_VAULT_PASSWORD_FILE ansible-lint

# --- Help ---

.PHONY: help

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*##' Makefile | awk -F ':.*## ' '{printf "  %-22s %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
