"""
Config Loader
-------------
Reads workflow and rules definitions from YAML files.
Workflows are fully configurable without code changes.
"""
import os
import yaml
from typing import Dict, Any


WORKFLOWS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "config", "workflows")


class ConfigLoader:
    _cache: Dict[str, Any] = {}

    @classmethod
    def load_workflow(cls, workflow_type: str) -> Dict[str, Any]:
        """
        Load a workflow config by name. Results are cached in memory.
        Raises FileNotFoundError if no matching config file exists.
        """
        if workflow_type in cls._cache:
            return cls._cache[workflow_type]

        filepath = os.path.join(WORKFLOWS_DIR, f"{workflow_type}.yaml")
        if not os.path.exists(filepath):
            available = cls.list_workflows()
            raise FileNotFoundError(
                f"Workflow '{workflow_type}' not found. Available: {available}"
            )

        with open(filepath, "r") as f:
            config = yaml.safe_load(f)

        cls._cache[workflow_type] = config
        return config

    @classmethod
    def reload_workflow(cls, workflow_type: str) -> Dict[str, Any]:
        """Force reload from disk — useful after config edits."""
        cls._cache.pop(workflow_type, None)
        return cls.load_workflow(workflow_type)

    @classmethod
    def list_workflows(cls):
        """Return names of all available workflow configs."""
        if not os.path.exists(WORKFLOWS_DIR):
            return []
        return [
            f.replace(".yaml", "")
            for f in os.listdir(WORKFLOWS_DIR)
            if f.endswith(".yaml")
        ]

    @classmethod
    def get_rules(cls, workflow_type: str, rules_set_name: str) -> list:
        """Extract a named rules set from a workflow config."""
        config = cls.load_workflow(workflow_type)
        rules_sets = config.get("workflow", {}).get("rules_sets", {})
        if rules_set_name not in rules_sets:
            raise KeyError(f"Rules set '{rules_set_name}' not found in workflow '{workflow_type}'")
        return rules_sets[rules_set_name]

    @classmethod
    def get_stages(cls, workflow_type: str) -> list:
        """Return ordered stage definitions for a workflow."""
        config = cls.load_workflow(workflow_type)
        return config.get("workflow", {}).get("stages", [])

    @classmethod
    def get_input_schema(cls, workflow_type: str) -> Dict[str, Any]:
        """Return input schema definition for validation."""
        config = cls.load_workflow(workflow_type)
        return config.get("workflow", {}).get("input_schema", {})
