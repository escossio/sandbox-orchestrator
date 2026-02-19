Siga obrigatoriamente docs/PROTOCOL_CODEX.md
Não faça perguntas; execute e mostre outputs; rode ./test_contract.sh após mudanças.
# Prompt - Runner

Contexto: sandbox-orchestrator.

Objetivo: detalhar a estrategia de runner e limites operacionais, sem implementar codigo.

Pontos obrigatorios:

- Ordem de escolha: shell -> docker -> vm (fallback)
- Criterios de selecao e limites de cada runner
- Docker sem privilegios (cap-drop, no-new-privileges, read-only + volume /work)
- Allowlist de dominios por job
- Limites de CPU/RAM/PIDs
- Artefatos: logs, screenshots (se usar browser), downloads, metadata.json
