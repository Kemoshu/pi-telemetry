VENV := .venv/bin
TF   := terraform -chdir=infra

.PHONY: venv test test-agent test-lambda lint fmt plan deploy destroy run-once

venv:
	python3 -m venv .venv
	$(VENV)/pip install -e "./agent[dev]" -r lambda/requirements-dev.txt

test: test-agent test-lambda

test-agent:
	$(VENV)/python -m pytest agent/tests -q

test-lambda:
	$(VENV)/python -m pytest lambda/tests -q

lint:
	$(VENV)/ruff check agent lambda
	terraform fmt -check -recursive infra

fmt:
	$(VENV)/ruff check --fix agent lambda
	terraform fmt -recursive infra

# Collect and print one real payload from this machine, no AWS needed.
run-once:
	$(VENV)/python -m pi_telemetry_agent --once

plan:
	$(TF) plan

deploy:
	$(TF) apply

destroy:
	$(TF) destroy
