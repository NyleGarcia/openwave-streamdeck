PLUGIN := dev.openwave.sdPlugin
PLUGINS_DIR := $(HOME)/.config/opendeck/plugins

.PHONY: test validate check package install clean

test:
	python3 -m unittest discover -s tests -t . -v

validate:
	python3 scripts/validate_plugin.py
	python3 -m compileall -q $(PLUGIN) scripts tests
	sh -n $(PLUGIN)/run.sh

check: validate test

package:
	@sh scripts/package.sh

# Copied rather than symlinked: OpenDeck resolves a plugin's property
# inspectors and layouts relative to the real directory, and refuses paths
# that canonicalise outside it.
install:
	rm -rf $(PLUGINS_DIR)/$(PLUGIN)
	mkdir -p $(PLUGINS_DIR)
	cp -r $(PLUGIN) $(PLUGINS_DIR)/$(PLUGIN)
	find $(PLUGINS_DIR)/$(PLUGIN) -name __pycache__ -type d -exec rm -rf {} +
	@echo "installed; restart OpenDeck"

clean:
	rm -rf dist
	find . -name __pycache__ -type d -exec rm -rf {} +
