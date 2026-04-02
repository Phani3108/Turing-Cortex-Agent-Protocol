# Cortex Agent CLI

A Python CLI tool to convert a YAML agent specification into configuration or prompt files for multiple agent runtimes (LangGraph, Semantic Kernel, Copilot Studio, and system prompt).

## Structure
- `agent_schema.yaml`: Example agent DSL schema
- `parser.py`: Parses the YAML agent spec
- `generators/`: Code generators for each target
- `cli.py`: Command-line interface

## Usage
1. Place your agent YAML spec in the project root.
2. Run the CLI to generate the desired output:
   ```sh
   python cli.py --input agent_schema.yaml --target langgraph
   ```

## Phase 1 Goals
- Define agent DSL in YAML
- Implement parser
- Implement code generators for all targets
- Provide CLI interface
