# Bot de chat: intenções e frases de exemplo

Bot **BotAtendimentoAurora** (Amazon Lex V2), idioma **Portuguese (Brazil)**, somente texto, região us-east-1, confidence threshold 0,70. Todas as frases e dados são fictícios.

O Connect usa um alias do bot e recebe o nome da intenção e o valor do campo `cpf`. Quem responde ao cliente é o fluxo do Connect, por isso **Fulfillment** e **Closing response** ficam vazios.

## Intenções

| Intenção | Slot | Observação |
|---|---|---|
| `SegundaViaBoleto` | `cpf` (AMAZON.AlphaNumeric, obrigatório) | O tipo é alfanumérico para não perder o zero do começo do CPF |
| `ConsultarExtrato` | `cpf` (AMAZON.AlphaNumeric, obrigatório) | Mesmo slot da intenção anterior |
| `FalarComAtendente` | nenhum | Não deve pedir CPF |
| `EncerrarConversa` | nenhum | |
| `FallbackIntent` | nenhum | Já vem no bot; deixar a resposta de encerramento vazia |

## SegundaViaBoleto
```
segunda via do boleto
quero a segunda via do meu boleto
preciso do boleto
quero meu boleto
gerar boleto
enviar boleto
me manda o boleto
boleto
segunda via
2ª via
quero pagar minha parcela
preciso pagar a parcela
como faço para pagar meu financiamento
meu boleto venceu
perdi meu boleto
```

## ConsultarExtrato
```
extrato
quero o extrato
preciso do extrato do meu contrato
ver o extrato do financiamento
consultar extrato
quero ver minhas parcelas
me mostra meu contrato
quero saber do meu financiamento
extrato do cdc
extrato do finame
```

## FalarComAtendente
```
falar com atendente
quero falar com um atendente
atendente
quero falar com uma pessoa
falar com um humano
me passa para um atendente
preciso de ajuda de uma pessoa
atendimento humano
quero falar com alguém
quero reclamar
tenho um problema com meu contrato
quero negociar minha dívida
quero renegociar
quero cancelar meu contrato
não consegui resolver
```

## EncerrarConversa
```
encerrar
encerrar conversa
quero encerrar
encerrar o chat
finalizar
finalizar atendimento
pode encerrar
pode fechar
tchau
até logo
é só isso
só isso, obrigado
não preciso de mais nada
era só isso, obrigada
já resolvi
```

## Aprendizados
- Frases com o slot `{cpf}` dentro do exemplo deixaram o bot permissivo demais (qualquer texto curto virava pedido), então foram removidas. O CPF é sempre perguntado depois do pedido.
- Frases genéricas como "quanto eu devo" ou "qual é o saldo" faziam perguntas fora do assunto caírem no extrato, e foram retiradas.
- Para testar, reinicie o painel de teste do Lex antes de cada frase, para a conversa anterior não influenciar.
- Depois de mudar as intenções: **Build**, nova **versão** e apontar o alias para a versão nova.

---

# Bot da pesquisa de satisfação (BotPesquisaAurora)

Bot de **uma intenção só**, para o Connect colher a nota de 1 a 5 no fim do chat. Usa a mesma role de serviço do outro bot, idioma Portuguese (Brazil), somente texto.

| Intenção | Slot |
|---|---|
| `AvaliarAtendimento` | `nota` (AMAZON.Number, obrigatório, 1 tentativa extra) |

```
nota {nota}
dou nota {nota}
minha nota é {nota}
avaliação {nota}
{nota} estrelas
{nota} pontos
```

**Por que um bot separado:** em um bot com várias intenções, um "5" digitado sozinho cai em qualquer uma delas. Em um bot com uma intenção só, o número cai sempre na avaliação.

O fluxo `DC_Chat_Pesquisa` grava a nota no atributo `nota_pesquisa_chat` (ou "sem resposta", se a pessoa não responder uma nota válida).
