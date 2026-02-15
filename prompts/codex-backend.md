# Prompt - Backend

Contexto: sandbox-orchestrator.

Objetivo: planejar a base de orquestracao de jobs, sem implementar codigo.

Pontos obrigatorios:

- Painel recebe comandos, cria job, roda worker efemero, salva artefatos e encerra worker
- Job lifecycle: queued, running, succeeded, failed
- Artefatos: logs, screenshots (se usar browser), downloads, metadata.json
- Observabilidade: logs estruturados por job com timestamps
- Seguranca: allowlist por job, limites de CPU/RAM/PIDs, docker sem privilegios
- Estrategia de runner: shell -> docker -> vm (fallback), com criterios claros
