# Contrato Minimo da API (v1)

Este documento define o contrato minimo para evitar regressao de rotas e formato de resposta.

## Versionamento

- Todas as rotas abaixo sao v1 e estao prefixadas por `/api`.
- Versao atual do contrato: v1.

## Politica de payload estrito (recursiva) — Opcao B (obrigatoria)

1) **Sem campos adicionais**
- **Nenhum campo adicional** (nao documentado) e permitido em **nenhum nivel**, incluindo objetos aninhados.
- Se aparecer um campo extra em qualquer objeto -> **resposta invalida**.

2) **Campos obrigatorios**
- A ausencia de um campo obrigatorio torna a resposta **invalida**.

3) **Campos opcionais — Regra B (obrigatoria)**
- Campos opcionais **devem sempre aparecer** no payload.
- Quando nao aplicaveis, **devem vir explicitamente como `null`**.
- Campos opcionais **nunca** devem ser omitidos.

4) **Nullabilidade**
- Um campo so pode ser `null` se o contrato declarar explicitamente `type | null`.

---

## Formato de timestamps (obrigatorio)

- Todo campo de tempo definido neste contrato deve ser:
  - **ISO-8601 em UTC com milissegundos e sufixo `Z`**
  - Formato obrigatorio: `YYYY-MM-DDTHH:MM:SS.sssZ`
- Exemplo: `2026-02-17T22:48:31.123Z`

Campos que seguem esta regra:
- `server_time_utc`
- `created_at`

---

## Rotas obrigatorias

### GET /api/health

- Status esperado: **200**
- Resposta JSON (exata):

```json
{
  "status": "ok",
  "db": "ok",
  "server_time_utc": "2026-02-17T22:48:31.123Z"
}
