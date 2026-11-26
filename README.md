# 📞💬 Atendimento Financeiro Demo: URA por voz e chat no site

Demonstração de atendimento ao cliente para o setor financeiro, construída na nuvem com **Amazon Connect**, **Amazon Lex**, **AWS Lambda**, **Supabase** e **Amazon SES**, em dois canais que compartilham o mesmo back-end:

- **📞 URA por voz:** o cliente liga, informa o CPF e escolhe o que precisa.
- **💬 Chat no site:** o cliente escreve o que precisa e um bot entende a intenção.

Projeto de demonstração da **Modo Piloto Consultoria de Tecnologia**, criado para mostrar como um atendimento moderno pode resolver pedidos comuns de um cliente de financiamento (segunda via de boleto e extrato) sem precisar de um atendente, e como encaminhar para uma pessoa, com contexto, quando for necessário.

> Todos os dados, nomes, CPFs e contratos deste projeto são **fictícios**.

**Neste README:** [📞 URA por voz](#-ura-por-voz) · [💬 Chat no site](#-chat-no-site) · [🧩 Base comum aos dois canais](#-base-comum-aos-dois-canais) · [📁 Estrutura](#-estrutura-do-repositório)

---

# 📞 URA por voz

## A experiência do cliente

O cliente liga, informa o CPF e escolhe o que precisa. Ele pode pedir a segunda via do boleto, ouvir o extrato do financiamento ou falar com uma pessoa.

## ✨ Destaques da URA

- **Horário de atendimento e feriados:** a URA confere se a central está aberta, com fuso de São Paulo e feriados cadastrados. Fora do horário, informa o expediente e encerra.
- **Identificação por CPF com proteção:** o CPF é validado antes de consultar o banco, e depois de 3 tentativas erradas, ou se o sistema falhar, o cliente é encaminhado a um atendente em vez de ficar preso.
- **2ª via de boleto por e-mail:** o cliente recebe o boleto em PDF no e-mail cadastrado.
- **Extrato de financiamento (CDC e FINAME):** com um contrato, a URA fala os dados dele. Com vários, envia o extrato de todos em um PDF único, para o cliente não precisar digitar números de contrato.
- **Menu que nunca prende o cliente:** a opção 0 repete o menu até 3 vezes, e opção inválida ou silêncio também têm limite de 3 tentativas. Depois disso, a ligação vai para um atendente.
- **Fila de espera com experiência cuidada:** música, aviso periódico a cada 60 segundos e, depois de 2 minutos, oferta de **retorno de ligação** mantendo o lugar na fila. Se a fila estiver cheia, o retorno também é oferecido.
- **Contexto para o atendente:** quando a ligação chega, o painel mostra o **nome** do cliente e o **CPF mascarado** (ex.: `***.456.789-**`).
- **Gravação com controle de acesso:** o aviso de gravação toca no início, a gravação fica em bucket S3 com criptografia, e só o perfil de supervisor acessa.
- **Pesquisa de satisfação em dois momentos:** depois do autoatendimento ("a solicitação foi atendida?") e depois do atendimento humano (nota de 1 a 5, com uma nova tentativa e registro de "sem resposta"). As notas ficam gravadas no registro de cada ligação.

## 🧠 Decisões técnicas da URA

- **Horário e feriados sem código.** A checagem usa os recursos nativos do Amazon Connect (*hours of operation* com exceções para feriados), sem Lambda.
- **Limites de tentativa em todo lugar.** Contadores (blocos *Loop*) impedem que CPF inválido, opção inválida ou silêncio prendam o cliente em um ciclo. O destino final é sempre uma pessoa.
- **Fila com fluxo próprio.** A espera, os avisos e o retorno de ligação ficam em um fluxo dedicado, separado do fluxo principal, o que facilita ajustar tempos e mensagens.
- **Gravação com acesso restrito.** As gravações ficam criptografadas, e só o perfil de supervisor consegue ouvi-las.

---

# 💬 Chat no site

## A experiência do cliente

O mesmo atendimento está disponível em um **chat dentro de um site de demonstração**. Em vez de menu por teclas, a pessoa escreve o que precisa e um bot (Amazon Lex, em português) entende a intenção: segunda via de boleto, extrato ou falar com um atendente.

**O bot atende 24 horas. Só o atendente humano depende do horário** (segunda a sexta, das 8h às 20h). Fora do horário, o chat informa o expediente e continua atendendo boleto e extrato.

## ✨ Destaques do chat

- **Bot que entende o que a pessoa escreve:** sem menu por teclas, o Amazon Lex reconhece o pedido em linguagem natural.
- **Bot 24 horas, atendente no horário:** fora do expediente o chat continua resolvendo boleto e extrato, e informa o horário de atendimento humano.
- **Encerrar a qualquer momento:** a pessoa pode dizer que era só isso e o chat se despede.
- **CPF com limite de tentativas:** quando o CPF não é encontrado, o chat orienta a tentar de novo e, depois de 3 vezes, chama um atendente.
- **Aviso de registro e fila com limite:** a conversa começa avisando que pode ser registrada, e se todos os atendentes estiverem ocupados o chat avisa e segue ajudando com boleto e extrato.
- **Site de demonstração publicado no GitHub Pages**, com o widget de chat do Amazon Connect (repositório separado).

## 🧠 Decisões técnicas do chat

- **Bot 24 horas, atendente no horário.** A checagem de horário só acontece no caminho do atendente. Fora do expediente, a conversa volta para o bot, em vez de ser encerrada.
- **Intenções enxutas e CPF como texto.** O CPF é lido como texto alfanumérico (e não como número) para não perder o zero do começo, e frases genéricas foram evitadas nos exemplos para o bot não confundir pedidos fora do assunto.
- **Idioma definido no fluxo.** O fluxo do chat define o idioma pt-BR antes de chamar o Lex, que só existe nesse idioma.
- **Fluxo e widget independentes do site.** Trocar o fluxo no widget do Connect não exige mexer no site.
- **Demonstração sem autenticação.** O widget não usa JWT, por ser um site estático. Em produção, a identificação do cliente deve vir de um backend.
- 
---

# 🧩 Base comum aos dois canais

A URA e o chat usam a **mesma instância do Amazon Connect**, as **mesmas Lambdas** e o **mesmo banco**. O que muda de um canal para o outro é só a forma de conversar.


| Camada | Tecnologia | Papel |
|---|---|---|
| Atendimento por voz e chat | Amazon Connect | Fluxos da URA e do chat, horário, fila, retorno de ligação, gravação e pesquisas |
| Bot de conversa | Amazon Lex (pt-BR, somente texto) | Entende o pedido do cliente no chat e extrai o CPF |
| Regras de negócio | AWS Lambda (Python 3.12) | Busca de cliente, boleto e extrato |
| Dados | Supabase (PostgreSQL) | Clientes, contratos e parcelas |
| E-mail | Amazon SES | Envio dos PDFs |
| Gravações | Amazon S3 + KMS | Armazenamento criptografado, acesso só para supervisor |

### Lambdas

| Função | O que faz |
|---|---|
| `buscarCliente` | Valida o CPF, busca o cliente e devolve nome, e-mail e CPF mascarado |
| `enviarBoleto` | Gera a 2ª via e envia o PDF por e-mail |
| `consultarExtrato` | Monta o extrato do financiamento e devolve a frase pronta |

## 🧠 Decisões técnicas compartilhadas

- **Lambdas sem bibliotecas externas.** O acesso ao Supabase usa só a biblioteca padrão do Python, e o PDF do boleto e do extrato é montado no próprio código. Isso deixa o deploy simples e sem dependências para manter.
- **Uma regra de negócio, dois canais.** Buscar cliente, enviar boleto e consultar extrato ficam no mesmo código, usado pela voz e pelo chat.
- **Dados que sobrevivem entre as etapas.** O Connect sobrescreve o resultado de cada Lambda a cada chamada, então os dados importantes, como CPF e nome, são copiados para atributos do contato logo depois.
- **Respostas prontas para falar.** A Lambda devolve a frase já montada, e o fluxo só fala ou escreve. Assim as regras ficam no código e o fluxo fica simples.
- **Privacidade por padrão.** O atendente vê apenas o CPF mascarado, os logs das Lambdas não registram dados pessoais, e as gravações ficam criptografadas com acesso restrito. Em produção, o CPF completo também deve usar atributos restritos ao fluxo.
- **Segurança desde o início.** Chaves ficam em variáveis de ambiente, o banco usa Row Level Security, e o repositório não contém chaves, IDs de conta nem telefone.

---

## 📁 Estrutura do repositório

```
ura-financeira-demo/
├── connect/     → fluxos do Amazon Connect, voz e chat (exportados e sem dados da conta)
├── lex/         → intenções e frases de exemplo do bot do chat
├── database/    → scripts SQL do banco
└── lambdas/     → funções Lambda em Python
    ├── buscarCliente/
    ├── enviarBoleto/
    └── consultarExtrato/
```

O site de demonstração do chat fica em um **repositório separado** (`site-demo-modopiloto`), publicado no GitHub Pages.

---

## 👩‍💻 Autoria

Desenvolvido por **Dayane Pereira Costa**, estudante de Análise e Desenvolvimento de Sistemas, em projeto de demonstração da **Modo Piloto Consultoria de Tecnologia**.
