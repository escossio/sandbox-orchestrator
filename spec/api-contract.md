# Contrato de API (rascunho)

## Objetivo

Definir contratos de entrada e saida do painel para criacao e acompanhamento de jobs.

## Endpoints propostos

- POST /jobs
  - cria um job a partir de um comando

- GET /jobs/{job_id}
  - retorna status, metadados e links de artefatos

## Regras principais

- Job lifecycle: queued -> running -> succeeded/failed
- Logs estruturados por job com timestamps
- Artefatos padrao: logs, screenshots (se usar browser), downloads, metadata.json

## Estrategia de runner

- Preferencia: shell -> docker -> vm
- Criterios:
  - shell para jobs simples e baixo risco
  - docker para isolamento moderado com imagem conhecida
  - vm como fallback para isolamento forte ou requisitos de kernel
