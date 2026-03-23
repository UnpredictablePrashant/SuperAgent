PYTHON ?= python3

.PHONY: install test compile ci docker-build

install:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e .

compile:
	$(PYTHON) -m compileall app.py gateway_server.py setup_ui.py superagent tasks mcp_servers

test:
	OPENAI_API_KEY=$${OPENAI_API_KEY:-test-openai-key} $(PYTHON) -m unittest discover -s tests -v

docker-build:
	docker build -t superagent-local .

ci: compile test docker-build
