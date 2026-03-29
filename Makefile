PYTHON ?= python3

.PHONY: bootstrap install uninstall compile unit smoke docs-check docker-smoke test verify ci docker-build

bootstrap:
	$(PYTHON) scripts/bootstrap_local_state.py

install: bootstrap
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e ".[dev]"

uninstall:
	$(PYTHON) -m pip uninstall -y kendr-runtime

compile:
	$(PYTHON) scripts/verify.py compile

unit:
	$(PYTHON) scripts/verify.py unit

smoke:
	$(PYTHON) scripts/verify.py smoke

docs-check:
	$(PYTHON) scripts/verify.py docs

docker-smoke:
	$(PYTHON) scripts/verify.py docker

test:
	$(PYTHON) scripts/verify.py unit

docker-build:
	$(PYTHON) scripts/verify.py docker

verify:
	$(PYTHON) scripts/verify.py compile unit smoke docs

ci:
	$(PYTHON) scripts/verify.py compile unit smoke docs docker --strict-docker
