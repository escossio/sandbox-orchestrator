# Arquitetura

## Visao geral

O sandbox-orchestrator recebe comandos, cria um job, executa um worker efemero, salva artefatos e encerra o worker ao final. Fluxo principal:

UI -> API -> queue -> runner -> artifacts store

## Componentes minimos (MVP)

- UI: entrada de comando e monitoramento de jobs
- API: valida parametros, cria job e expõe estado
- queue: fila interna para ordenar execucoes
- runner: executa o job conforme estrategia escolhida
- artifacts store: logs, screenshots, downloads, metadata.json

Decisoes explicitas:

- Persistencia minima por job: /srv/sandbox-orchestrator/var/jobs/<job_id>/metadata.json como baseline.
- Retries: attempts[] com attempt_id e timestamps; tentativa nova nao apaga a anterior.
- Retencao/limpeza: politica padrao 7 dias, cleanup periodico.

## Evolucoes futuras

- Fila externa (ex.: Redis, SQS, Pub/Sub)
- Banco de dados para historico, busca e agregacoes
- Streaming de logs em tempo real
- Cache de downloads e artefatos

## Ciclo de vida do job

Estados canonicos: queued, running, succeeded, failed.

Transicoes sao registradas com timestamps e vinculadas ao job_id.
