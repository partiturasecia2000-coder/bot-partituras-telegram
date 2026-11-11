# Atualização para a versão 2

O ponto de entrada continua sendo `main.py`. A configuração do Discloud foi preservada.

## Aplicar o pacote

1. Guarde uma cópia da aplicação atual e dos dados persistentes da hospedagem.
2. Atualize os arquivos de código com todo o conteúdo deste ZIP, incluindo os novos diretórios de rotas. Atualize com o bot parado para não misturar versões durante a execução.
3. Mantenha o `.env`, o `config.json`, o `.config_backup.json` e o `acervo_partituras.db` de produção. Eles não estavam no ZIP recebido e não foram recriados neste pacote. Não substitua dados reais pela configuração de exemplo.
4. Instale as dependências de `requirements.txt` e inicie pelo mesmo `main.py`. O Discloud continua responsável pela instalação e inicialização conforme a configuração já existente.
5. Confira no Telegram: `/painel`, edição de boas-vindas, uma mensagem agendada, busca inline e envio ao destino de teste escolhido por você.

## Acesso administrativo no privado

O privado deixou de conceder administração automaticamente a qualquer pessoa.

Por padrão, o bot verifica se o usuário é administrador ou proprietário de algum grupo/canal vinculado. O bot precisa conseguir consultar a participação nesse chat. Em falhas de consulta, não concede acesso.

Para controlar exatamente quem administra pelo privado, configure a variável `BOT_ADMIN_IDS` com IDs numéricos separados por vírgula. Exemplo de formato, com IDs fictícios:

```text
BOT_ADMIN_IDS=123456789,987654321
```

Alternativamente, adicione `"panel_admin_ids": [123456789]` ao `config.json` existente, preservando os outros campos. Quando uma lista explícita está definida, ela determina o acesso no privado; a variável de ambiente tem precedência sobre o campo JSON. Sem lista explícita, vale a verificação nos chats vinculados.

As permissões em grupos continuam baseadas no status de administrador do grupo atual. A busca inline pública não foi restringida. As operações de administração do acervo passaram a exigir autorização.

## Validação local, sem conectar ao Telegram

```text
python -m pip install -r requirements.txt
python -m compileall -q main.py config.py modules tests
python tests/check_regression.py
python -m unittest discover -s tests -p "test_*.py" -v
```

Os testes usam dados isolados e um token fictício quando necessário. O polling e o envio real são substituídos nos testes. Não execute `main.py` simultaneamente com a instância de produção usando o mesmo token.

## Estrutura

- `modules/panel_handlers/callback_routes/`: ações dos botões, agrupadas por assunto.
- `modules/panel_handlers/input_routes/`: edição de textos, mídias, configurações e transmissões.
- `modules/panel_support.py`: dependências compartilhadas do painel.
- `modules/storage.py`: leitura e gravação atômica de JSON.
- `modules/access.py`: autorização administrativa no privado e proteção dos comandos do acervo.
- `modules/acervo_database.py`: persistência SQLite com fechamento explícito das conexões.
- `requirements.txt`: versões exatas testadas; `requirements.in`: requisitos abertos da versão recebida.

## Recuperação

Se o JSON principal estiver inválido, o bot tenta restaurar o backup. Se ambos estiverem inválidos, interrompe a carga e preserva os arquivos, em vez de sobrescrever os dados com padrões. Nesse caso, restaure uma cópia válida antes de reiniciar.

A gravação atômica evita arquivos parcialmente escritos. Ela não transforma operações separadas de leitura e gravação em transações, nem coordena múltiplas instâncias. Continue executando uma instância do bot por conjunto de dados.
