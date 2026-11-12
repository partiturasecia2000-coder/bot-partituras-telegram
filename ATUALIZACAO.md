# Atualizar para a versão 6 — menu

1. Pare o bot e aplique o ZIP completo.
2. Preserve `.env`, `config.json`, `.config_backup.json`, `acervo_partituras.db`, `agendamentos.db` e a pasta `backups/`. Se houver uma recuperação interrompida, mantenha também `.restore_journal.json` e `.restore-transactions/`.
3. Inicie o bot e abra `/painel` para ver o menu novo.
4. No privado, envie `/menu` para renovar o teclado com os atalhos curtos. Os botões anteriores continuam aceitos.

## Organização

- **Nova postagem / Histórico:** atalhos no início do painel.
- **Segurança:** bloqueios, limites, palavras proibidas e exceções.
- **Entrada e boas-vindas:** mensagem geral, grupos e aprovação de entrada.
- **Partituras e acervo:** busca, canais e sincronização.
- **Mensagens e respostas:** recorrências, respostas automáticas e YouTube.
- **Limpeza:** comandos, avisos e instruções de limpeza manual.
- **Sistema e backups:** grupos/canais, horário, registros, backup e restauração.

Os estados aparecem por escrito. Botões como **Ativar antispam** informam a ação que será aplicada. Use **Voltar** para retornar à área anterior e **Início** para abrir o painel principal. Para sair de uma edição em andamento, use `/cancelar`.

Fonte e tema seguem as preferências do Telegram. A prévia HTML fornecida é ilustrativa, usa dados fictícios e funciona sem conexão.

## Recursos da versão anterior

Postagens continuam exigindo prévia e confirmação. `/falar`, `/anunciar`, `/canal` e `/comunicado` usam o mesmo histórico em `/agendados`. Backups continuam disponíveis apenas a administradores no privado; restauração mantém validação, confirmação e cópia anterior. Após restaurar, revise as programações antigas antes de reativá-las.

Validação offline:

```text
python -m pip install -r requirements.txt
python -m compileall -q main.py config.py modules tests
python tests/check_regression.py
python -m unittest discover -s tests -p "test_*.py" -v
```

Não execute duas instâncias com o mesmo token.
