# PROTOCOLO OBRIGATÓRIO (NÃO PERGUNTAR, SÓ EXECUTAR)

Este protocolo é vinculante para qualquer agente operando neste repositório.

## Regras

- Sempre ler e respeitar `docs/CONTRACT.md` antes de qualquer alteração.
- Não pedir confirmação em nenhuma etapa.
- Após qualquer mudança em arquivos, rodar `./test_contract.sh`.
- Falhar imediatamente quando `DATABASE_URL` estiver ausente com a mensagem EXATA: "DATABASE_URL is required".
- Com `DATABASE_URL` presente: `GET /api/health` deve responder `200` com JSON estrito e timestamps em UTC com milissegundos e sufixo `Z` no formato `YYYY-MM-DDTHH:MM:SS.sssZ`.
- Definition of Done: só finalizar com comandos executados e trecho do output provando sucesso.
- Qualquer comportamento fora do protocolo = erro de execução.
