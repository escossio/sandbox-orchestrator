# sandbox-orchestrator

## Visao geral

O sandbox-orchestrator e um painel que recebe comandos, cria um job, executa um worker efemero, salva artefatos e encerra o worker ao final. O foco e orquestrar execucoes isoladas com rastreabilidade por job.

## Ciclo de vida de job

Estados canonicos:

- queued
- running
- succeeded
- failed

Transicoes sao unidirecionais e registradas com timestamp.

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
- docker: usado quando precisa de dependencias controladas e isolamento moderado. Deve ser a opcao padrao quando houver imagem disponivel. Executa sem privilegios e com filesystem read-only.
- vm: fallback para jobs que exigem kernel especifico, isolamento forte ou ferramentas que nao cabem em container. Provisionamento e mais lento e caro, entao so deve ser usado quando shell/docker nao atendem.

## Observabilidade

Logs estruturados por job, com timestamps consistentes (UTC) e correlacao por job_id e attempt_id.

## Segurança (resumo)

Detalhes completos em `docs/security.md`.

- allowlist de dominios por job
- limites de CPU/RAM/PIDs
- docker sem privilegios (cap-drop, no-new-privileges, read-only + volume /work)
