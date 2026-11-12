# Atualização para a versão 5

Pare o bot e aplique o ZIP completo. O ponto de entrada e a configuração Discloud continuam iguais. Preserve os arquivos de dados já existentes: `.env`, `config.json`, `.config_backup.json`, `acervo_partituras.db`, `agendamentos.db` e a pasta `backups/`.

## Enviar mensagens

Use normalmente `/falar`, `/anunciar`, `/canal` ou `/comunicado`. Agora todos passam pela prévia e pelo mesmo histórico, tanto em envios imediatos quanto agendados.

1. Prepare a mensagem, responda a uma mídia ou use o comando na legenda do arquivo.
2. Escolha o destino, quando houver seletor.
3. Confira texto, anexo, destinos, horário, tópico e fixação na prévia. Navegue entre as páginas para ver o conteúdo e a lista completa de destinos.
4. Use **Ver conteúdo no privado** para conferir a postagem formatada. Essa amostra vai somente ao seu privado; abra a conversa com o bot primeiro.
5. Pressione **Confirmar envio** ou **Confirmar agendamento**. Sem essa confirmação, não há postagem aos destinos.
6. Consulte `/agendados` para acompanhar os resultados. As novas tentativas seletivas continuam excluindo os destinos já entregues e os envios sem confirmação.

A prévia expira em 30 minutos e só pode ser confirmada pelo autor na mensagem original. Se o horário escolhido já passou, prepare um novo agendamento. PDFs/documentos, fotos, vídeos, áudios e voz são suportados; o `/anunciar` mantém a fixação e o cabeçalho de comunicado.

## Restaurar um backup

1. No privado, abra `/painel` → **Sistema** → **Backup** → **Restaurar backup**.
2. Envie o ZIP gerado pelo bot, com até 20 MB.
3. Aguarde a validação. Confira os arquivos e quantidades na prévia, incluindo a política de pausa das programações antigas.
4. Confirme em até cinco minutos ou cancele. A cópia do estado atual será criada antes da substituição.
5. Ao terminar, use **Baixar cópia anterior** e guarde o arquivo. Ele também permanece na pasta `backups/` da aplicação.

O comando `/restaurar` também aceita o ZIP ou arquivos JSON/DB antigos; todos passam pela revisão e confirmação. O comando `/backup` gera um ZIP completo e só o entrega no privado de administradores.

Token, ambiente e destinos atuais de backup/logs são mantidos. IDs administrativos explícitos atuais e seu ID permanecem autorizados; IDs administrativos do backup não são ativados.

Depois de restaurar, confira as configurações e `/tarefas`. Recorrências, YouTube e backups automáticos precisam ser reativados pelos controles do painel após revisão. Transmissões antigas não são disparadas automaticamente. Exclusões antigas restauradas ficam pausadas, sem reativação em lote; novas exclusões funcionam normalmente. Restaurar não remove mensagens que já chegaram ao Telegram.

Se a operação informar que o bot precisa reiniciar, reinicie a aplicação no Discloud. Não apague `.restore_journal.json` nem `.restore-transactions/` se existirem: são usados para recuperar uma troca interrompida antes da inicialização.

## Validação offline

```text
python -m pip install -r requirements.txt
python -m compileall -q main.py config.py modules tests
python tests/check_regression.py
python -m unittest discover -s tests -p "test_*.py" -v
```

Os testes simulam a rede e usam arquivos isolados. Executar `main.py` inicia o bot real. Mantenha apenas uma instância com o mesmo token.
