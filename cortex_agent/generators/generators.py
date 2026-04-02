from parser import AgentSpec

def generate_langgraph(agent: AgentSpec) -> str:
    return f"""# LangGraph Agent Config\nname: {agent.name}\nrole: {agent.role}\ninstructions: |\n  {agent.instructions}\ntools:\n" + "\n".join([
        f"  - name: {tool['name']}\n    description: {tool['description']}" for tool in agent.tools
    ])

def generate_semantic_kernel(agent: AgentSpec) -> str:
    return f"""# Semantic Kernel Agent Config\n[Agent]\nName = {agent.name}\nRole = {agent.role}\nInstructions = '''{agent.instructions}'''\nTools = {', '.join([tool['name'] for tool in agent.tools])}\n"""

def generate_copilot_studio(agent: AgentSpec) -> str:
    return f"""// Copilot Studio Agent\nName: {agent.name}\nRole: {agent.role}\nInstructions: {agent.instructions}\nTools: {', '.join([tool['name'] for tool in agent.tools])}\n"""

def generate_system_prompt(agent: AgentSpec) -> str:
    return f"""System Prompt:\nYou are {agent.name}, a {agent.role}. {agent.instructions}\nAvailable tools: {', '.join([tool['name'] for tool in agent.tools])}\n"""
