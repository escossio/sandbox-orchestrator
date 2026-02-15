# Especificacao de Job (schema conceitual)

Este documento define os campos esperados para um job. Nao e um schema executavel.

## Campos obrigatorios

- job_id: identificador unico
- command: comando original recebido pelo painel
- status: queued | running | succeeded | failed
- created_at: timestamp UTC

## Campos opcionais

- allowlist_domains: lista de dominios permitidos
- runner_strategy: shell | docker | vm
- time_limit_seconds
- cpu_limit
- ram_limit_mb
- pid_limit
- artifacts:
  - logs
  - screenshots
  - downloads
  - metadata.json

## Metadados

- attempt_id
- exit_code
- started_at
- finished_at
- durations
