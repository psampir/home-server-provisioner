# Load user overrides if present (see .env.example)
-include .env

# Export variables so scripts and Ansible can access them
export SSH_PUBKEY_FILE
export VM_CPUS
export VM_MEMORY
export VM_DISK
export VM_IMAGE
export ANSIBLE_PRIVATE_KEY_FILE

# --- Setup ---

.PHONY: setup

setup: ## Install Ansible, ansible-lint, and required collections
	@./scripts/setup.sh

# --- Test environment ---

.PHONY: test-env-create test-env-destroy test-env-status

test-env-create: ## Create test VMs and generate inventory
	./scripts/test-env.sh create

test-env-destroy: ## Destroy all test VMs and clean up
	./scripts/test-env.sh destroy

test-env-status: ## Show test VM status
	./scripts/test-env.sh status

# --- Help ---

.PHONY: help

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*##' Makefile | awk -F ':.*## ' '{printf "  %-20s %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
