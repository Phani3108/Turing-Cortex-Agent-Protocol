import yaml

class AgentSpec:
    def __init__(self, data):
        self.name = data.get('name')
        self.role = data.get('role')
        self.instructions = data.get('instructions')
        self.tools = data.get('tools', [])
        self.memory = data.get('memory', {})

    @staticmethod
    def from_yaml(path):
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
        return AgentSpec(data)
