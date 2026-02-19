# sandbox-orchestrator

## Visao geral

O sandbox-orchestrator e um painel que recebe comandos, cria um job, executa um worker efemero, salva artefatos e encerra o worker ao final. O foco e orquestrar execucoes isoladas com rastreabilidade por job.

## Non-goals

- nao e um sistema de CI/CD completo
- nao substitui um scheduler de batch generalista
- nao oferece persistencia indefinida de artefatos
- nao pretende ser um executor de workloads de longa duracao

## Ciclo de vida de job

Estados canonicos:

- queued
- running
- succeeded
- failed

Transicoes sao unidirecionais e registradas com timestamp.

## Layout de artefatos

Layout canonico em `/srv/sandbox-orchestrator/var/jobs/<job_id>/`:

- metadata.json
- artifacts.json (manifest com sha256 e size_bytes)
- logs/runner.ndjson
- logs/worker.ndjson
- screenshots/ (quando houver browser)
- downloads/

## Artefatos por job

Cada job pode produzir os seguintes artefatos padrao:

- logs estruturados
- screenshots (apenas quando o runner usa navegador)
- downloads (arquivos emitidos pelo job)
- metadata.json (metadados do job, versao, limites, tempos e status)

## Estrategia de runner

Ordem de selecao e fallback:

1. shell
2. docker
3. vm

A escolha e baseada em requisitos do job e limites do ambiente:

- shell: usado quando o job e simples, sem dependencias de sistema e com baixo risco. Limites de tempo e recursos sao mais baixos.
- docker: usado quando precisa de dependencias controladas e isolamento moderado. Deve ser a opcao padrao recomendada quando possivel e houver imagem disponivel. Executa sem privilegios e com filesystem read-only.
- vm: fallback para jobs que exigem kernel especifico, isolamento forte ou ferramentas que nao cabem em container. Provisionamento e mais lento e caro, entao so deve ser usado quando shell/docker nao atendem.

## Retencao

Retencao padrao de artefatos: 7 dias (configuravel).

## Modelo de confianca

- o orquestrador e confiavel para registrar metadados, aplicar limites e anexar artefatos
- runners sao considerados nao confiaveis e sao isolados por camada (shell, docker ou vm)
- somente artefatos e metadados explicitamente coletados sao persistidos
- acesso a rede, filesystem e recursos e limitado por politica e por job

## Exemplo de job

1. usuario envia comando e parametros
2. orquestrador cria `job_id`, grava `metadata.json` e muda estado para `queued`
3. runner selecionado inicia, executa o worker e emite logs para `logs/runner.ndjson` e `logs/worker.ndjson`
4. artefatos sao listados em `artifacts.json` com sha256 e size_bytes
5. job finaliza e transita para `succeeded` ou `failed`

## Observabilidade

Logs estruturados por job, com timestamps consistentes (UTC) e correlacao por job_id e attempt_id.

## Segurança (resumo)

Detalhes completos em `docs/security.md`.

- allowlist de dominios por job
- limites de CPU/RAM/PIDs
- docker sem privilegios (cap-drop, no-new-privileges, read-only + volume /work)

## Dev workflow

- Leia `docs/CONTRACT.md` e `docs/PROTOCOL_CODEX.md`.
- Rodar testes: `./test_contract.sh`.
- Subir dev rapidamente: `scripts/run_dev.sh`.

## Rodar API + runner (shell)

1. Exporte `DATABASE_URL` (ex: `sqlite:////tmp/sandbox.db`).
2. Inicie a API: `scripts/run_dev.sh`.
3. Inicie o runner: `scripts/run_runner.sh`.

Logs locais:

- Runner: `logs/runner.ndjson`
- Worker: `logs/worker.ndjson`
