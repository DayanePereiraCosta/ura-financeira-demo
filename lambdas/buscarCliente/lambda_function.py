"""
Lambda: buscarCliente
Chamada pelo fluxo do Amazon Connect (bloco "Invocar funcao AWS Lambda").

Entrada (parametro do bloco):  cpf  (so numeros, 11 digitos)
  -> se o cpf nao vier, tenta buscar pelo telefone de quem esta ligando.

Saida (tudo texto, formato simples que o Connect aceita):
  encontrado = "true" ou "false"
  erro       = "true" se o banco nao respondeu
  cpf, nome, primeiro_nome, email, pontos

Variaveis de ambiente (configuradas no console da Lambda, NUNCA no codigo):
  SUPABASE_URL         ex: https://abcdefgh.supabase.co
  SUPABASE_SECRET_KEY  chave sb_secret_...
"""
import json
import os
import re
import urllib.parse
import urllib.request


def consultar_cliente(coluna, valor):
    """Consulta a tabela clientes no Supabase (API REST) e devolve a lista de linhas."""
    url_base = os.environ["SUPABASE_URL"].rstrip("/")
    chave = os.environ["SUPABASE_SECRET_KEY"]

    params = urllib.parse.urlencode({
        "select": "cpf,nome,email,telefone,pontos",
        coluna: f"eq.{valor}",
        "limit": "1",
    })
    requisicao = urllib.request.Request(
        f"{url_base}/rest/v1/clientes?{params}",
        # A chave secreta vai SOMENTE no cabecalho apikey
        headers={"apikey": chave, "Accept": "application/json"},
    )
    with urllib.request.urlopen(requisicao, timeout=5) as resposta:
        return json.loads(resposta.read().decode("utf-8"))


def lambda_handler(event, context):
    detalhes = event.get("Details", {})
    parametros = detalhes.get("Parameters", {})

    cpf = re.sub(r"\D", "", str(parametros.get("cpf", "")))  # deixa so os numeros
    endpoint = detalhes.get("ContactData", {}).get("CustomerEndpoint") or {}
    telefone = endpoint.get("Address", "")

    try:
        if cpf:
            if len(cpf) != 11:
                return {"encontrado": "false", "erro": "false", "motivo": "cpf_invalido"}
            linhas = consultar_cliente("cpf", cpf)
        elif telefone:
            linhas = consultar_cliente("telefone", telefone)
        else:
            return {"encontrado": "false", "erro": "false", "motivo": "sem_dados"}
    except Exception as e:
        # Nunca imprima a chave ou dados do cliente nos logs
        print(f"ERRO ao consultar o banco: {type(e).__name__}: {e}")
        return {"encontrado": "false", "erro": "true"}

    if not linhas:
        print("Cliente nao encontrado")
        return {"encontrado": "false", "erro": "false", "motivo": "nao_encontrado"}

    cliente = linhas[0]
    print("Cliente encontrado")
    return {
        "encontrado": "true",
        "erro": "false",
        "cpf": cliente["cpf"],
        "nome": cliente["nome"],
        "primeiro_nome": cliente["nome"].split()[0],
        "email": cliente["email"],
        "pontos": str(cliente["pontos"]),
    }