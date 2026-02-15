# Arquitetura

## Visao geral

O sandbox-orchestrator e um painel que recebe comandos, cria um job, executa um worker efemero, salva artefatos e encerra o worker ao final. O fluxo principal e:

1. Entrada de comando no painel
2. Criacao do job e persistencia do estado
3. Provisionamento de runner (shell, docker ou vm)
4. Execucao do worker efemero
5. Coleta de artefatos e logs
6. Encerramento e limpeza

## Componentes logicos

- Painel: interface de entrada e monitoramento de jobs
- Orquestrador: valida parametros, enfileira e coordena execucao
- Runner: executa o job conforme estrategia escolhida
- Armazenamento de artefatos: logs, screenshots, downloads, metadata.json

## Ciclo de vida do job

Estados canonicos: queued, running, succeeded, failed.

Transicoes sao registradas com timestamps e vinculadas ao job_id.
