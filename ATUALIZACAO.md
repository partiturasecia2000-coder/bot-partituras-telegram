# Atualizar para a versão 3 — agendamentos

1. Pare o bot e aplique o ZIP completo, incluindo os dois novos módulos de agendamento. Mantenha o mesmo `main.py` e a configuração Discloud existente.
2. Preserve `.env`, `config.json`, `.config_backup.json` e `acervo_partituras.db`. Nas próximas atualizações, preserve também `agendamentos.db`, criado automaticamente nesta versão para guardar exclusões pendentes.
3. Inicie o bot. Envie `/tarefas` como administrador e confira o estado das rotinas. Os ciclos começam após aproximadamente 3 segundos; uma rotina sem nada para enviar também pode concluir normalmente.
4. Confira `/agendados`. Se houver envio interrompido, verifique nos destinos o que chegou antes de usar **Reenviar**. O reenvio pode repetir mensagens já entregues.
5. Para uma conferência prática, programe uma mensagem para um destino seu, espere a entrega e confira a exclusão automática, se configurada. Um reinício antes do prazo de exclusão agora preserva essa tarefa no banco.

## Comportamento após reinício

- Transmissão ainda pendente cujo horário passou: processada pelo próximo ciclo.
- Transmissão que estava em envio: exibida como interrompida para revisão; não é reenviada automaticamente.
- Mensagem recorrente diária com horário fixo: pode executar após o horário do dia atual, se ainda não foi registrada como enviada nesse horário e os filtros permitirem. Dias anteriores não são repostos.
- Exclusão registrada por esta versão: continua pendente no banco e é tentada quando vencer, ou no próximo ciclo se já estiver vencida.

O comando `/tarefas` informa a execução dos ciclos; não confirma a entrega de cada mensagem. Exclusões com falhas permanentes ou cinco tentativas sem sucesso ficam contabilizadas como falha. Timers de captcha e respostas atrasadas mantêm o funcionamento anterior.

## Permissões e testes

A regra de acesso da versão 2 permanece: no privado, administração em um chat vinculado acessível ao bot ou uma lista explícita em `BOT_ADMIN_IDS`/`panel_admin_ids`. A busca inline continua pública.

Validação offline na raiz do projeto:

```text
python -m pip install -r requirements.txt
python -m compileall -q main.py config.py modules tests
python tests/check_regression.py
python -m unittest discover -s tests -p "test_*.py" -v
```

Não execute duas instâncias com o mesmo token. Os testes simulam chamadas ao Telegram; a execução de `main.py` inicia o bot real.
