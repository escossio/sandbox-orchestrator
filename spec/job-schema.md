# Especificacao de Job (schema detalhado)

Este documento descreve o schema de Job em Markdown (nao e JSON Schema). Os campos abaixo devem estar presentes conforme indicado. Tipos sao conceituais e as observacoes detalham regras e semantica.

## Campos de nivel raiz

- job_version (string)
  - Observacoes: versao do schema/contrato do job. Ex.: "1.0".
- job_id (string)
  - Observacoes: identificador unico e imutavel do job.
- command (string)
  - Observacoes: comando original recebido pelo painel.
- parsed_intent (obj opcional)
  - Observacoes: intencao parseada do comando; estrutura livre, pode estar ausente.
- status (queued|running|succeeded|failed)
  - Observacoes: status atual do job no pipeline.
- created_at (timestamp UTC ISO-8601)
  - Observacoes: data/hora de criacao do job em UTC (ex.: "2026-02-15T12:34:56Z").

## policy (obj)

- allowlist_domains (array string)
  - Observacoes: lista de dominios explicitamente permitidos para acesso de rede.
- limits (obj)
  - time_limit_seconds (int)
    - Observacoes: tempo maximo total permitido para execucao.
  - cpu_limit (string)
    - Observacoes: limite de CPU (ex.: "2 cores" ou "50% quota").
  - ram_limit_mb (int)
    - Observacoes: limite de memoria RAM em megabytes.
  - pid_limit (int)
    - Observacoes: limite de processos.

## runner (obj)

- requested (shell|docker|vm|null)
  - Observacoes: solicitacao explicita do usuario; pode ser null.
- selected (shell|docker|vm)
  - Observacoes: runner efetivamente escolhido pelo sistema.
- selection_reason (string curta)
  - Observacoes: justificativa resumida da selecao do runner.

## attempts (array)

Cada tentativa representa uma execucao do job. Novas tentativas NAO apagam as anteriores.

- attempt_id (string)
  - Observacoes: identificador unico da tentativa.
- status (queued|running|succeeded|failed)
  - Observacoes: status da tentativa.
- started_at (timestamp UTC)
  - Observacoes: inicio da tentativa em UTC (ISO-8601).
- finished_at (timestamp UTC)
  - Observacoes: fim da tentativa em UTC (ISO-8601).
- exit_code (int|null)
  - Observacoes: codigo de saida do processo; null se nao aplicavel ou ainda nao terminou.
- error_summary (string|null)
  - Observacoes: resumo curto do erro quando status=failed; null caso contrario.

## artifacts_manifest (array)

Representa o que existe em `/srv/sandbox-orchestrator/var/jobs/<job_id>/`.

- name (string)
  - Observacoes: nome logico do artefato.
- path (string)
  - Observacoes: caminho relativo dentro da pasta do job.
- sha256 (string)
  - Observacoes: hash SHA-256 do conteudo.
- size_bytes (int)
  - Observacoes: tamanho em bytes.
- content_type (string)
  - Observacoes: MIME type (ex.: "text/plain").
- created_at (timestamp UTC)
  - Observacoes: data/hora de criacao do artefato em UTC (ISO-8601).

## Exemplo completo (YAML)

```yaml
job_version: "1.0"
job_id: "job_01HZYX3R4S1A2B3C4D5E6F7G8"
command: "rg --files | wc -l"
parsed_intent:
  action: "count_files"
  tool: "rg"
status: "succeeded"
created_at: "2026-02-15T14:05:12Z"
policy:
  allowlist_domains:
    - "example.com"
    - "api.example.org"
  limits:
    time_limit_seconds: 900
    cpu_limit: "2 cores"
    ram_limit_mb: 2048
    pid_limit: 256
runner:
  requested: "docker"
  selected: "docker"
  selection_reason: "isolamento necessario para dependencia nativa"
attempts:
  - attempt_id: "att_01HZYX3S9X4Q5W6E7R8T9Y0U1"
    status: "failed"
    started_at: "2026-02-15T14:06:10Z"
    finished_at: "2026-02-15T14:06:40Z"
    exit_code: 137
    error_summary: "limite de memoria excedido"
  - attempt_id: "att_01HZYX3VB2C3D4E5F6G7H8I9J0"
    status: "succeeded"
    started_at: "2026-02-15T14:07:05Z"
    finished_at: "2026-02-15T14:07:22Z"
    exit_code: 0
    error_summary: null
artifacts_manifest:
  - name: "logs"
    path: "logs/attempt_att_01HZYX3VB2C3D4E5F6G7H8I9J0.txt"
    sha256: "b7a8d5e1a6f1c5e3f2d4a9c0b1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8"
    size_bytes: 4821
    content_type: "text/plain"
    created_at: "2026-02-15T14:07:23Z"
  - name: "metadata"
    path: "metadata.json"
    sha256: "4f3c2b1a0e9d8c7b6a5f4e3d2c1b0a9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c3"
    size_bytes: 912
    content_type: "application/json"
    created_at: "2026-02-15T14:07:23Z"
```
