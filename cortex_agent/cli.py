import argparse
from parser import AgentSpec
from generators.generators import (
    generate_langgraph,
    generate_semantic_kernel,
    generate_copilot_studio,
    generate_system_prompt,
)

target_map = {
    'langgraph': generate_langgraph,
    'semantic-kernel': generate_semantic_kernel,
    'copilot-studio': generate_copilot_studio,
    'system-prompt': generate_system_prompt,
}

def main():
    parser = argparse.ArgumentParser(description='Cortex Agent CLI')
    parser.add_argument('--input', required=True, help='Path to agent YAML spec')
    parser.add_argument('--target', required=True, choices=target_map.keys(), help='Target output')
    parser.add_argument('--output', help='Output file (optional)')
    args = parser.parse_args()

    agent = AgentSpec.from_yaml(args.input)
    output = target_map[args.target](agent)

    if args.output:
        with open(args.output, 'w') as f:
            f.write(output)
    else:
        print(output)

if __name__ == '__main__':
    main()
