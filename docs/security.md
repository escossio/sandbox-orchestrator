# Seguranca

## Controles principais

- Allowlist de dominios por job para qualquer acesso externo
- Limites de CPU, RAM e PIDs por job
- Runner docker sem privilegios:
  - cap-drop (remover capacidades)
  - no-new-privileges
  - filesystem read-only com volume de trabalho em /work

## Isolamento e acesso

- Cada job roda em um worker efemero e descartavel
- Credenciais temporarias devem ser injetadas por job e expiradas ao final
- Acesso a rede deve ser restrito ao allowlist

## Auditoria

- Logs estruturados por job com timestamps
- Registro de mudancas de estado do job e limites aplicados
