# Atualizar para a versão 4

Pare o bot, aplique o ZIP completo e mantenha os arquivos de dados existentes: `.env`, `config.json`, `.config_backup.json`, `acervo_partituras.db` e `agendamentos.db`. O ponto de entrada e a configuração Discloud continuam iguais. Não é necessário criar outro banco nesta versão: os resultados das transmissões ficam no JSON de configurações já existente.

## Como usar o acompanhamento

1. Prepare o envio pelo `/comunicado`. Vale tanto para **Enviar agora** quanto para agendar.
2. Abra **Ver resultados** na mensagem de confirmação, ou use `/agendados` e escolha a transmissão na lista paginada. A lista também apresenta histórico concluído.
3. Confira cada destino: entregue, falha confirmada, sem confirmação ou ainda não enviado. As partes confirmadas e o número de tentativas ficam disponíveis no detalhe.
4. Se houver falhas confirmadas, use **Tentar somente falhas confirmadas**. Os destinos já entregues não entram nessa tentativa.
5. Se um reinício deixou destinos que ainda não começaram, use **Continuar destinos não enviados**. Destinos sem confirmação não entram: confira-os no Telegram antes de preparar um envio separado, se necessário.

O acompanhamento detalhado começa nos novos envios do assistente. Envios antigos não possuem esses dados. Comandos avulsos `/falar`, `/anunciar` e `/canal` mantêm os fluxos anteriores; use `/comunicado` para o histórico novo.

## Listas e exclusões

Use **Anterior/Próxima** para acessar todos os itens nas listas do painel. A seleção de destinos deixa de esconder canais depois dos seis primeiros; o seletor de varredura do acervo também permite navegar por todos os canais.

Ações destrutivas manuais agora mostram uma confirmação. Leia o item/nome apresentado e pressione **Confirmar exclusão** ou **Cancelar**. A confirmação expira em dois minutos, só funciona para a pessoa que pediu e não pode ser reutilizada. Após reinício ou alteração do item, abra uma nova confirmação.

No `/limpar`, apenas mensagens anteriores ao comando original são consideradas. A limpeza automática de manutenção e as rotinas de moderação existentes mantêm seu funcionamento.

As regras de acesso e o comando `/tarefas` da versão anterior continuam disponíveis.

## Validação offline

```text
python -m pip install -r requirements.txt
python -m compileall -q main.py config.py modules tests
python tests/check_regression.py
python -m unittest discover -s tests -p "test_*.py" -v
```

Os testes simulam a rede. Executar `main.py` inicia o bot real; mantenha apenas uma instância com o mesmo token.
