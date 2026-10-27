# 🤖 Bot de Gerenciamento para Grupo do Telegram

Bot completo desenvolvido em Python para automatizar a moderação e gestão de grupos no Telegram.

---

## 🌟 Funcionalidades Principais

1. **Boas-Vindas Personalizadas (Welcome)**
   - Envia mensagem calorosa para novos membros com o nome dele e do grupo.
   - Suporte a variáveis dinâmicas: `{name}`, `{username}`, `{group}`, `{id}`.
   - **Auto-exclusão configurável**: apaga a mensagem de boas-vindas após X segundos para não poluir o grupo.
   - Apaga opcionalmente as notificações de sistema padrão (*"Fulano entrou no grupo"*).

2. **Antispam & Filtro de Links**
   - **Bloqueio de Links externos**: apaga mensagens com URLs e alerta o usuário.
   - **Bloqueio de Convites do Telegram**: bloqueia links como `t.me/...` ou `t.me/joinchat/...`.
   - **Bloqueio de Encaminhamentos**: impede o envio de mensagens encaminhadas de canais de spam.
   - **Palavras Proibidas (Blacklist)**: lista customizável de termos proibidos (ex: promessas de ganhos rápidos, golpes, palavras de baixo calão).
   - **Lista de Domínios Permitidos**: você pode permitir domínios específicos (ex: `youtube.com`).

3. **Anti-Flood**
   - Detecta usuários enviando mensagens muito rapidamente (ex: mais de 5 mensagens em 5 segundos).
   - Silencia temporariamente o infrator por X minutos para restabelecer a ordem.

4. **Detecção de Mensagens Repetidas (Anti-Repeat)**
   - Bloqueia mensagens idênticas enviadas em sequência pelo mesmo usuário em um intervalo de tempo.
   - Suporta detecção de repetição de **textos, figurinhas (stickers), fotos e GIFs**.
   - Apaga a repetição e envia um aviso temporário de alerta.

5. **Comandos de Moderação Administrativa**
   - `/config` ou `/painel` - **Menu Interativo**: abre o painel visual com botões para ativar/desativar regras, ajustar tempos e ver status em tempo real.
   - `/regras` - Exibe as regras oficiais do grupo.
   - `/ban` (respondendo a uma mensagem) - Bane o usuário permanentemente.
   - `/kick` (respondendo a uma mensagem) - Expulsa o membro do grupo.
   - `/mute [minutos]` (respondendo a uma mensagem) - Silencia o membro temporariamente.
   - `/unmute` (respondendo a uma mensagem) - Restaura a capacidade de enviar mensagens.
   - `/limpar [quantidade]` - Apaga rapidamente as últimas N mensagens do chat (ex: `/limpar 15`).
   - `/ajuda` - Exibe a lista de comandos disponíveis.

> ℹ️ *Administradores do grupo estão isentos das regras de antispam, anti-flood e repetição.*

---

## 🚀 Passo a Passo: Como Colocar o Bot para Funcionar

### Passo 1: Criar o Bot no Telegram e obter o Token
1. No seu Telegram, busque por **`@BotFather`** (verifique se possui o selo azul de verificado).
2. Envie o comando `/newbot`.
3. Escolha um nome de exibição para o bot (ex: `Moderador do Meu Grupo`).
4. Escolha um nome de usuário (username) terminado em `bot` (ex: `MeuGrupoMod_bot`).
5. O `@BotFather` enviará uma mensagem contendo o seu **Token da API** (algo como `7123456789:AAEjK...`). Guarde esse código!

---

### Passo 2: Configurar o Token no Projeto
Abra a pasta do projeto: `D:\Movidos\Desktop\Bot para o grupo Telegram`

Você pode colar o Token de duas formas (escolha a que preferir):

- **Opção A (Mais fácil)**: Abra o arquivo `config.json` e cole o seu token no campo `"telegram_bot_token"`:
  ```json
  "telegram_bot_token": "7123456789:AAEjK..."
  ```
- **Opção B**: Crie um arquivo com o nome `.env` na pasta e adicione:
  ```env
  TELEGRAM_BOT_TOKEN=7123456789:AAEjK...
  ```

---

### Passo 3: Adicionar o Bot ao seu Grupo no Telegram
1. Abra o seu grupo no Telegram.
2. Vá nas configurações do grupo > **Adicionar Membros** (ou Administradores).
3. Busque pelo username do seu bot (o que você criou no `@BotFather`).
4. **MUITO IMPORTANTE:** Promova o bot a **Administrador** do grupo e conceda as seguintes permissões:
   - ✅ **Apagar mensagens** *(Delete messages)*
   - ✅ **Restringir/Banir usuários** *(Restrict/Ban users)*
   - ✅ **Fixar mensagens** *(Pin messages - opcional)*
   - ✅ **Convidar usuários por link** *(opcional)*

*(Se o bot não for Administrador com permissão de apagar e restringir, ele não conseguirá deletar spams nem mutar infratores).*

---

### Passo 4: Iniciar o Bot
Basta dar dois cliques no arquivo:
👉 **`run.bat`**

O terminal abrirá, ativará o ambiente e mostrará:
```
🤖 Iniciando Bot de Gerenciamento do Grupo...
✅ Bot configurado com sucesso! Conectando aos servidores do Telegram...
```

Pronto! O bot já está 100% operacional no seu grupo! 🎉

---

## ⚙️ Como Personalizar as Configurações

Todas as regras e mensagens estão no arquivo **`config.json`**. Você pode editar esse arquivo com qualquer editor de texto (Bloco de Notas, VS Code, etc.):

```json
{
  "welcome": {
    "enabled": true,
    "delete_service_messages": true,
    "delete_welcome_after_seconds": 60,
    "message": "👋 Olá, {name}! Seja bem-vindo(a) ao grupo *{group}*!\n\n📌 Não se esqueça de ler as regras enviando o comando /regras."
  },
  "antispam": {
    "enabled": true,
    "block_links": true,
    "block_telegram_invites": true,
    "block_forwards": true,
    "banned_words": [
      "ganhe dinheiro",
      "renda extra",
      "investimento garantido",
      "trabalhe em casa ganhando",
      "clique no link",
      "crypto pump",
      "robô do pix",
      "plataforma pagando",
      "t.me/joinchat",
      "cassino online",
      "tigrinho"
    ]
  },
  "antiflood": {
    "enabled": true,
    "max_messages": 5,
    "time_window_seconds": 5,
    "mute_duration_minutes": 5
  },
  "antirepeat": {
    "enabled": true,
    "max_repeated": 2,
    "time_window_seconds": 60
  }
}
```

---

## 📁 Estrutura de Arquivos do Projeto

```
D:\Movidos\Desktop\Bot para o grupo Telegram\
├── .venv/                   # Ambiente virtual Python
├── modules/
│   ├── utils.py             # Cache de administradores e exclusão agendada
│   ├── welcome.py           # Módulo de boas-vindas
│   ├── antispam.py          # Módulo antispam, links e anti-flood
│   ├── antirepeat.py        # Módulo de detecção de mensagens repetidas
│   └── admin_commands.py    # Comandos administrativos (/ban, /mute, /limpar, etc.)
├── .env.example             # Exemplo de arquivo de variáveis de ambiente
├── config.json              # Configurações gerais (textos, tempos, palavras proibidas)
├── config.py                # Leitor das configurações
├── main.py                  # Ponto de entrada do bot
├── requirements.txt         # Dependências do projeto
├── run.bat                  # Executável rápido para Windows
└── README.md                # Este guia
```
