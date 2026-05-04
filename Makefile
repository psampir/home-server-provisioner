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

TEST_INVENTORY = inventories/test
PROD_INVENTORY = inventories/production

# --- Ansible (production) ---

.PHONY: bootstrap provision

bootstrap: ## First run on fresh hosts (production)
	ansible-playbook playbooks/bootstrap.yml -i $(PROD_INVENTORY) -e 'ansible_user={{ bootstrap_user }}' -kK

provision: ## Run full site playbook (production)
	ansible-playbook playbooks/site.yml -i $(PROD_INVENTORY)

# --- Test environment ---

.PHONY: test-env-create test-env-destroy test-env-status test-bootstrap test-provision

test-env-create: ## Create test VMs and generate inventory
	./scripts/test-env.sh create

test-env-destroy: ## Destroy all test VMs and clean up
	./scripts/test-env.sh destroy

test-env-status: ## Show test VM status
	./scripts/test-env.sh status

test-bootstrap: ## First run on test VMs
	ansible-playbook playbooks/bootstrap.yml -i $(TEST_INVENTORY) -e 'ansible_user={{ bootstrap_user }}' -kK

test-provision: ## Run full site playbook against test VMs
	ansible-playbook playbooks/site.yml -i $(TEST_INVENTORY)

# --- Setup ---

.PHONY: setup init-config

setup: ## Install Ansible, ansible-lint, and required collections
	@./scripts/setup.sh

init-config: ## Create config/ directory for tracking private settings
	@./scripts/init-config.sh

# --- Help ---

.PHONY: help

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*##' Makefile | awk -F ':.*## ' '{printf "  %-20s %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
