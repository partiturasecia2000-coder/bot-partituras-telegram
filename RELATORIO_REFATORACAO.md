# Versão 4 — transmissões e navegação do painel

Base: `bot_discloud_agendamentos_v3.zip`. O pacote anterior foi preservado. Nenhum deploy nem envio real foi realizado.

## Transmissões por destino

- As transmissões imediatas do assistente e as agendadas por `/comunicado` usam o mesmo motor e histórico persistente no `config.json` existente.
- No primeiro disparo, a lista de destinos é normalizada, deduplicada e congelada. Novos canais vinculados depois não entram por acidente em uma tentativa posterior.
- Cada destino registra estado, número de tentativas, IDs das partes confirmadas, horário e motivo resumido da falha. Textos divididos e fotos/vídeos com legendas longas registram as partes separadamente.
- O relatório distingue **entregue**, **falha confirmada**, **sem confirmação** e **ainda não enviado**. Falta de permissão, destino inexistente, mídia inválida e limitações do Telegram recebem explicações sem exibir mensagens técnicas brutas.
- **Tentar somente falhas confirmadas** exclui todos os destinos já entregues, sem confirmação ou não enviados. **Continuar destinos não enviados** trata apenas os destinos que ainda não começaram. As reservas do agendador impedem duas tentativas simultâneas do mesmo registro no processo.
- Timeout, queda durante a requisição ou falha após entrega parcial ficam sem confirmação e não são reenviados automaticamente. A recuperação após reinício mantém os destinos confirmados, marca o destino em envio como incerto e devolve os destinos apenas enfileirados ao estado de não enviados.
- O fallback de formatação deixou de repetir pedidos após erros de rede; rejeições confirmadas de formatação continuam permitindo os formatos alternativos. Falha ao fixar a mensagem ou ao enviar o relatório ao criador não transforma uma entrega em falha de envio.
- A autocorreção de IDs confirmados pelo Telegram e o registro no canal de auditoria foram mantidos.

## Paginação e confirmações

- Paginação nas transmissões/histórico, resultados por destino, grupos/canais, respostas automáticas, destinos do assistente, links permitidos, canais do YouTube, palavras proibidas, links de entrada do acervo e seleção de canais para varredura. Recorrências e usuários da whitelist mantêm a paginação anterior.
- Endereços longos deixam de ser incorporados aos callbacks: identificadores curtos evitam ultrapassar o limite de tamanho dos botões.
- Confirmação antes de zerar o acervo, remover textos do acervo, apagar todas as palavras proibidas, excluir recorrências/respostas, desvincular chats, remover monitoramento do YouTube, remover links permitidos e executar `/limpar` no chat.
- A confirmação é vinculada ao usuário, chat e mensagem; expira em dois minutos e só pode ser consumida uma vez. Cancelamento, reinício e perda de permissão impedem a execução. Se o item configurável mudar entre a prévia e a confirmação, é necessário abrir e confirmar novamente.
- `/limpar` limita a seleção às mensagens anteriores ao comando original; mensagens novas não entram na limpeza.

## Validação

**77 testes automatizados aprovados**, incluindo os 38 anteriores e 39 novos. Os novos casos verificam confirmação por destino, novas tentativas seletivas, destino congelado, timeout sem repetição, entregas parciais, falha de gravação após aceitação pelo Telegram, reinício durante a rede, envio imediato com histórico, correção de IDs, falha ao fixar/notificar, proteção e expiração de confirmações, permissões, paginação e acesso aos últimos canais do acervo.

Também passaram a checagem de 52 funções de menus/importações/persistência/SQLite/durações, compilação dos arquivos Python e verificação de referências globais dos módulos alterados. A integridade e o conteúdo do ZIP final foram conferidos.

Testes locais/offline em Windows, Python 3.14.3 e dependências fixadas da versão 3; chamadas externas simuladas. Não houve validação conectada ao Telegram, YouTube ou Discloud.

## Atualização e limites

Configuração Discloud, `Procfile`, `config.py`, configuração de exemplo, dependências e mídias foram preservados. Nenhuma credencial foi removida ou divulgada. Preserve `.env`, `config.json`, `.config_backup.json`, `acervo_partituras.db` e `agendamentos.db` da hospedagem ao atualizar.

O histórico detalhado é criado para novos envios do assistente `/comunicado`, imediatos ou agendados. Envios antigos não possuem confirmações por destino e não recebem botão de reenvio seletivo. Comandos avulsos como `/falar`, `/anunciar` e `/canal`, assim como as mensagens recorrentes, mantêm seus fluxos próprios e não são convertidos para esse histórico nesta versão. Use o assistente para obter o acompanhamento novo.

“Entregue” significa que a API confirmou o envio, não que alguém leu a mensagem. Não existe garantia de entrega exatamente uma vez em uma queda entre Telegram e gravação local; resultados sem confirmação exigem conferência no destino e permanecem fora das novas tentativas. Os motivos exibidos são categorias resumidas, sem guardar o texto bruto das exceções. Mantenha uma única instância por token/conjunto de dados.
