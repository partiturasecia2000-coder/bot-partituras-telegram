# Agendamentos — versão 3

Fonte: `bot_discloud_melhorado_v2.zip`, na pasta do projeto indicada pelo usuário. O ZIP anterior foi preservado. Nenhum deploy ou envio real foi realizado.

## Problemas encontrados e alterações

- Recorrência, modo noturno e YouTube tinham dois acionadores periódicos: um loop contínuo e jobs do APScheduler. Os acionadores duplicados foram removidos.
- `modules/scheduler.py` agora controla seis ciclos: recorrência, transmissões, modo noturno, YouTube, backup/relatórios e exclusões. Cada ciclo executa em sequência consigo mesmo; uma rotina lenta ou com erro não impede o avanço das demais. O serviço inicia no `post_init` e cancela/aguarda suas tarefas no `post_stop`.
- Os cinco primeiros ciclos verificam condições a cada 10 segundos, após 3 segundos iniciais; o intervalo configurado do YouTube continua sendo respeitado pela rotina existente. Exclusões são consultadas a cada segundo. A duração das operações e a rede podem acrescentar atraso.
- Transmissões são reservadas como `sending` no JSON antes de iniciar a task. Disparo manual e automático usam a mesma reserva e o mesmo controle de tarefas, evitando duas execuções simultâneas do mesmo ID no processo. Se a gravação falhar, o envio não é iniciado.
- Ao reiniciar, transmissões deixadas em `sending` viram `interrupted`; falhas inesperadas viram `failed`. Elas aparecem em `/agendados` com aviso para conferir os destinos antes de reenviar. Não são retomadas automaticamente, pois parte da mensagem pode já ter sido entregue. Envios em andamento ficam visíveis e não oferecem cancelamento que não seria efetivamente aplicado.
- Agendamentos pendentes vencidos continuam sendo processados ao iniciar. Recorrências com horário fixo diário passam a recuperar o horário do dia atual após atraso/reinício, respeitando filtros de datas/dias e o registro do último horário executado. Não há reposição dos dias anteriores.
- Exclusões que passam por `schedule_message_deletion` ficam em `agendamentos.db`. Esse novo banco é criado automaticamente e não contém tokens. Reinícios retomam as exclusões pendentes, inclusive vencidas. Falhas transitórias têm até cinco tentativas; mensagens já apagadas são consideradas concluídas. Falta de permissão ou restrição permanente fica registrada como falha.
- Os backups automáticos incluem o novo banco. Ambos os bancos SQLite são copiados usando a API de backup do SQLite, evitando cópias brutas de arquivos em uso.
- O progresso de recorrência, YouTube e backup é mesclado com uma carga atual do JSON, reduzindo o risco de substituir configurações ou transmissões criadas enquanto uma rotina aguardava a rede.
- `/tarefas`, exclusivo para administradores, mostra o estado dos ciclos, transmissões ativas e quantidade de exclusões pendentes/com falha.

## Validação

- 38 testes automatizados aprovados, incluindo os 19 testes anteriores e 19 novos testes do agendador.
- Cobertura nova: inicialização idempotente, integração dos hooks da aplicação, encerramento e cancelamento das tasks, isolamento entre ciclos, retomada de exclusões após reabrir o banco, prazos futuros, tentativas limitadas, mensagens já apagadas, ausência de job duplicado, reserva única de transmissão, falha de gravação, falha de envio, recuperação do estado após reinício, recorrência diária atrasada e preservação de edições recentes.
- Backup testado com fila persistente recuperável e sem arquivos temporários residuais.
- Checagem anterior de 52 funções de menus, importações, persistência, SQLite e durações aprovada. A tela de transmissões mudou intencionalmente para exibir estados de envio e interrupção.
- Compilação e integridade do ZIP verificadas.
- Testes locais em Windows, Python 3.14.3, usando as mesmas dependências fixadas da versão 2; chamadas externas simuladas. Não houve validação conectada ao Telegram, YouTube ou Discloud.

## Preservação e limites

`discloud.config`, `Procfile`, `config.py`, configuração de exemplo, dependências e mídias permanecem como na versão 2. O ponto de entrada continua sendo `main.py`. Nenhum token foi removido ou divulgado.

Mantenha os dados existentes da hospedagem: `.env`, `config.json`, `.config_backup.json`, `acervo_partituras.db` e, após o primeiro uso desta versão, `agendamentos.db`. O pacote não inclui bancos ou configurações de produção.

Exclusões agendadas pela versão anterior apenas em memória não podem ser recuperadas retroativamente. Timers específicos de captcha, respostas atrasadas e ações avulsas que não passam pelo helper de exclusão não foram migrados para persistência nesta etapa. O JobQueue permanece disponível para esses usos pontuais.

Não há garantia de entrega exatamente uma vez: uma queda entre a aceitação de uma mensagem pelo Telegram e sua confirmação local continua sendo uma situação ambígua. Por isso, envios interrompidos exigem revisão manual e podem repetir mensagens se reenviados. A aplicação deve continuar usando uma única instância por token/conjunto de dados; o controle desta versão não é um coordenador distribuído.
