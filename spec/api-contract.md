# Contrato de API (painel/orquestrador)

## Objetivo

Definir a API minima do painel/orquestrador para criacao e acompanhamento de jobs, incluindo logs e artefatos.

## Regras gerais

- Base path: `/api`
- Todas as respostas incluem `request_id` (string) e `server_time_utc` (timestamp ISO-8601).
- `job_id` e sempre string.

## Endpoints

### 1) POST /api/jobs

Cria um job a partir de um comando.

**Request JSON**

- `command` (string, required)
- `policy` (obj, opcional)
- `policy.allowlist_domains` (array de string, opcional)
- `policy.limits` (obj, opcional)
- `runner` (obj, opcional)
- `runner.requested` (enum: shell|docker|vm|null, opcional)

**Response 201 JSON**

- `job` (obj resumido)
- `job.job_id` (string)
- `job.status` (string)
- `job.created_at` (timestamp ISO-8601)
- `job.runner` (obj, opcional)
- `job.runner.selected` (enum: shell|docker|vm, opcional; presente se ja decidido)
- `job.links` (obj)

**Exemplo**

Request:
```json
{
  "command": "python -m pipeline.run --source s3://bucket/input.csv",
  "policy": {
    "allowlist_domains": ["s3.amazonaws.com"],
    "limits": {
      "max_runtime_seconds": 900,
      "max_output_mb": 250
    }
  },
  "runner": {
    "requested": "docker"
  }
}
```

Response 201:
```json
{
  "job": {
    "job_id": "job_01HTZ9R1KQY7Q2N3B0J6WJ3F2A",
    "status": "queued",
    "created_at": "2026-02-15T12:34:56Z",
    "runner": {
      "selected": "docker"
    },
    "links": {
      "self": "/api/jobs/job_01HTZ9R1KQY7Q2N3B0J6WJ3F2A",
      "logs": "/api/jobs/job_01HTZ9R1KQY7Q2N3B0J6WJ3F2A/logs",
      "artifacts": "/api/jobs/job_01HTZ9R1KQY7Q2N3B0J6WJ3F2A/artifacts"
    }
  },
  "request_id": "req_01HTZ9R2B1T8MZ3B4FQ2Z6K1W0",
  "server_time_utc": "2026-02-15T12:34:56Z"
}
```

**Codigos de erro**

- 400 Validation
- 403 Policy
- 429 Rate limit
- 500 Internal

Formato padrao:
```json
{
  "error": {
    "code": "validation_error",
    "message": "command is required",
    "details": {
      "field": "command"
    }
  },
  "request_id": "req_01HTZ9R2B1T8MZ3B4FQ2Z6K1W0",
  "server_time_utc": "2026-02-15T12:34:56Z"
}
```

### 2) GET /api/jobs

Lista jobs com filtros e paginacao por cursor.

**Query params**

- `status` (opcional)
- `q` (opcional, busca por `command`)
- `limit` (opcional, default 50, max 200)
- `cursor` (opcional)

**Response 200 JSON**

- `items` (array de jobs resumidos)
- `next_cursor` (string|null)

**Exemplo**

Request:
```json
{
  "status": "running",
  "q": "pipeline",
  "limit": 2,
  "cursor": "cur_01HTZ9S0Q5ZQ9B5K7X2A4T0P6H"
}
```

Response 200:
```json
{
  "items": [
    {
      "job_id": "job_01HTZ9R1KQY7Q2N3B0J6WJ3F2A",
      "status": "running",
      "created_at": "2026-02-15T12:34:56Z",
      "runner": {
        "selected": "docker"
      },
      "links": {
        "self": "/api/jobs/job_01HTZ9R1KQY7Q2N3B0J6WJ3F2A"
      }
    },
    {
      "job_id": "job_01HTZ9S7A6QZ7K4F3M2T1N8C9V",
      "status": "running",
      "created_at": "2026-02-15T12:35:10Z",
      "links": {
        "self": "/api/jobs/job_01HTZ9S7A6QZ7K4F3M2T1N8C9V"
      }
    }
  ],
  "next_cursor": "cur_01HTZ9T2K7B1N5V9C8M4Q3J2L0",
  "request_id": "req_01HTZ9T2K7B1N5V9C8M4Q3J2L0",
  "server_time_utc": "2026-02-15T12:36:00Z"
}
```

**Codigos de erro**

- 400 Validation
- 429 Rate limit
- 500 Internal

Formato padrao:
```json
{
  "error": {
    "code": "rate_limited",
    "message": "too many requests"
  },
  "request_id": "req_01HTZ9T2K7B1N5V9C8M4Q3J2L0",
  "server_time_utc": "2026-02-15T12:36:00Z"
}
```

### 3) GET /api/jobs/{job_id}

Retorna o job completo.

**Response 200 JSON**

- `job` (obj completo)
- `job.policy` (obj)
- `job.runner` (obj)
- `job.attempts` (array)
- `job.artifacts_manifest` (array)

**Exemplo**

Response 200:
```json
{
  "job": {
    "job_id": "job_01HTZ9R1KQY7Q2N3B0J6WJ3F2A",
    "status": "succeeded",
    "created_at": "2026-02-15T12:34:56Z",
    "completed_at": "2026-02-15T12:40:12Z",
    "command": "python -m pipeline.run --source s3://bucket/input.csv",
    "policy": {
      "allowlist_domains": ["s3.amazonaws.com"],
      "limits": {
        "max_runtime_seconds": 900,
        "max_output_mb": 250
      }
    },
    "runner": {
      "requested": "docker",
      "selected": "docker"
    },
    "attempts": [
      {
        "attempt_id": "att_01HTZ9W2H1P6K3Y9D8A7S5N4F2",
        "status": "succeeded",
        "started_at": "2026-02-15T12:35:00Z",
        "finished_at": "2026-02-15T12:40:12Z"
      }
    ],
    "artifacts_manifest": [
      {
        "name": "stdout.log",
        "content_type": "text/plain",
        "size_bytes": 18204
      },
      {
        "name": "metadata.json",
        "content_type": "application/json",
        "size_bytes": 2412
      }
    ],
    "links": {
      "logs": "/api/jobs/job_01HTZ9R1KQY7Q2N3B0J6WJ3F2A/logs",
      "artifacts": "/api/jobs/job_01HTZ9R1KQY7Q2N3B0J6WJ3F2A/artifacts"
    }
  },
  "request_id": "req_01HTZ9X2Y3K7Q9V5M1C8F4P6D0",
  "server_time_utc": "2026-02-15T12:41:00Z"
}
```

**Codigos de erro**

- 404 Not found

Formato padrao:
```json
{
  "error": {
    "code": "not_found",
    "message": "job not found"
  },
  "request_id": "req_01HTZ9X2Y3K7Q9V5M1C8F4P6D0",
  "server_time_utc": "2026-02-15T12:41:00Z"
}
```

### 4) GET /api/jobs/{job_id}/logs

Recupera logs do job.

**Query params**

- `attempt_id` (opcional; se ausente, usa o attempt mais recente)
- `stream` (0|1) (opcional; se 1, streaming SSE linha-a-linha)
- `tail` (opcional int, default 200)

**Response 200**

- `stream=0`: JSON com `lines` (array) e `cursor`
- `stream=1`: `text/event-stream`, eventos SSE linha-a-linha

**Exemplo**

Request:
```json
{
  "attempt_id": "att_01HTZ9W2H1P6K3Y9D8A7S5N4F2",
  "stream": 0,
  "tail": 3
}
```

Response 200 (stream=0):
```json
{
  "lines": [
    {
      "ts": "2026-02-15T12:35:02Z",
      "level": "info",
      "message": "starting pipeline"
    },
    {
      "ts": "2026-02-15T12:35:10Z",
      "level": "info",
      "message": "loaded 1500 records"
    },
    {
      "ts": "2026-02-15T12:40:12Z",
      "level": "info",
      "message": "pipeline completed"
    }
  ],
  "cursor": "logcur_01HTZ9Z2M4V7S8N2H5B6Q1A0R9",
  "request_id": "req_01HTZ9Z2M4V7S8N2H5B6Q1A0R9",
  "server_time_utc": "2026-02-15T12:40:13Z"
}
```

Response 200 (stream=1):
```json
{
  "content_type": "text/event-stream",
  "notes": "Cada evento SSE contem uma linha de log serializada em JSON."
}
```

**Codigos de erro**

- 404 Not found
- 409 Conflict (job ainda nao tem logs)
- 500 Internal

Formato padrao:
```json
{
  "error": {
    "code": "logs_unavailable",
    "message": "logs not available yet"
  },
  "request_id": "req_01HTZ9Z2M4V7S8N2H5B6Q1A0R9",
  "server_time_utc": "2026-02-15T12:40:13Z"
}
```

### 5) GET /api/jobs/{job_id}/artifacts

Lista artefatos do job.

**Response 200 JSON**

- `artifacts_manifest` (array)
- `links` (obj)

**Exemplo**

Response 200:
```json
{
  "artifacts_manifest": [
    {
      "name": "stdout.log",
      "content_type": "text/plain",
      "size_bytes": 18204
    },
    {
      "name": "metadata.json",
      "content_type": "application/json",
      "size_bytes": 2412
    }
  ],
  "links": {
    "download_base": "/api/jobs/job_01HTZ9R1KQY7Q2N3B0J6WJ3F2A/artifacts"
  },
  "request_id": "req_01HTZA22J1M3K5P7Q9V2C4B6N8",
  "server_time_utc": "2026-02-15T12:42:10Z"
}
```

**Codigos de erro**

- 404 Not found
- 500 Internal

Formato padrao:
```json
{
  "error": {
    "code": "not_found",
    "message": "job not found"
  },
  "request_id": "req_01HTZA22J1M3K5P7Q9V2C4B6N8",
  "server_time_utc": "2026-02-15T12:42:10Z"
}
```

### 6) GET /api/jobs/{job_id}/artifacts/{name}

Download de um artefato especifico.

**Response**

- Download do artefato com `Content-Type` correto.

**Exemplo**

Response 200:
```json
{
  "content_type": "application/json",
  "content_disposition": "attachment; filename=metadata.json"
}
```

**Codigos de erro**

- 404 Not found
- 500 Internal

Formato padrao:
```json
{
  "error": {
    "code": "artifact_not_found",
    "message": "artifact not found"
  },
  "request_id": "req_01HTZA4H2Q3W5E7R9T1Y3U5I7O",
  "server_time_utc": "2026-02-15T12:43:00Z"
}
```
