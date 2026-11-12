"""
Lambda: consultarExtrato   (DEMONSTRACAO - todos os dados sao ficticios)

O que faz, em ordem:
  1. Recebe o CPF do cliente (parametro "cpf" do bloco Lambda do Connect)
  2. Busca no Supabase: cliente, contratos ativos e parcelas nao pagas
  3. Calcula parcelas pagas e saldo devedor aproximado de cada contrato
  4. Gera um PDF de extrato (1 pagina por contrato, ate 5 contratos)
  5. Envia o PDF por e-mail (Amazon SES) para o e-mail cadastrado
  6. Devolve ao Connect uma frase pronta para ser falada:
       - 1 contrato: fala os dados completos do contrato
       - varios contratos: fala um resumo curto

Variaveis de ambiente (configure no console da Lambda):
  SUPABASE_URL           ex: <SUPABASE_URL>
  SUPABASE_SECRET_KEY    chave <API_KEY>
  EMAIL_REMETENTE        e-mail VERIFICADO no Amazon SES
Opcional:
  NOME_EMPRESA           padrao "Modo Piloto Consultoria de Tecnologia"
"""
import json
import os
import urllib.parse
import urllib.request
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from email.message import EmailMessage
from zoneinfo import ZoneInfo

import boto3
from botocore.exceptions import ClientError

CENTAVO = Decimal("0.01")
NOME_EMPRESA = os.environ.get("NOME_EMPRESA", "Modo Piloto Consultoria de Tecnologia")
MAX_CONTRATOS = 5  # limite por e-mail, para respeitar o tempo maximo de 8 s do Connect
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]
NOME_MODALIDADE = {
    "CDC": "CDC (Crédito Direto ao Consumidor)",
    "FINAME": "FINAME (Financiamento de Máquinas e Equipamentos)",
}


def hoje_br():
    # A Lambda roda em UTC; usamos o fuso de Sao Paulo para a data nao virar cedo demais
    return datetime.now(ZoneInfo("America/Sao_Paulo")).date()


# ----------------------------------------------------------------------------
# Supabase (API REST)
# ----------------------------------------------------------------------------
def consultar(tabela, filtros):
    url_base = os.environ["SUPABASE_URL"].rstrip("/")
    chave = os.environ["SUPABASE_SECRET_KEY"]
    url = f"{url_base}/rest/v1/{tabela}?{urllib.parse.urlencode(filtros)}"
    req = urllib.request.Request(url, headers={"apikey": chave, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ----------------------------------------------------------------------------
# Formatacao
# ----------------------------------------------------------------------------
def dinheiro(v):
    return Decimal(str(v)).quantize(CENTAVO, ROUND_HALF_UP)


def brl(v):
    s = f"{dinheiro(v):,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def data_br(d):
    return d.strftime("%d/%m/%Y")


def fala_valor(v):
    v = dinheiro(v)
    reais, centavos = int(v), int((v * 100) % 100)
    txt = f"{reais} {'real' if reais == 1 else 'reais'}"
    if centavos:
        txt += f" e {centavos} {'centavo' if centavos == 1 else 'centavos'}"
    return txt


def fala_data(d):
    return f"{d.day} de {MESES[d.month - 1]}"


def mascarar_cpf(cpf):
    return f"{cpf[:3]}.***.***-{cpf[-2:]}"


def fala_modalidade(m):
    return "Finame" if m == "FINAME" else "C D C"  # soletrado para a voz nao ler "cedecê" errado


# ----------------------------------------------------------------------------
# Regras do extrato
# ----------------------------------------------------------------------------
def montar_extrato(contrato, nao_pagas, hoje):
    """Calcula pagas, proxima parcela e saldo aproximado de um contrato.

    parcelas pagas = numero da parcela nao paga mais antiga - 1
    saldo aproximado = parcelas restantes x valor da parcela (sem juros futuros)
    """
    total = int(contrato["parcelas_total"])
    valor_parcela = dinheiro(contrato["valor_parcela"])
    if nao_pagas:
        proxima = nao_pagas[0]
        pagas = max(0, min(total, int(proxima["numero"]) - 1))
        venc = date.fromisoformat(proxima["vencimento"])
        em_atraso = venc < hoje
        proxima_info = {"numero": int(proxima["numero"]), "vencimento": venc,
                        "valor": dinheiro(proxima["valor"])}
    else:
        pagas, proxima_info, em_atraso = total, None, False
    saldo = valor_parcela * (total - pagas)
    return {
        "contrato_id": contrato["contrato_id"],
        "produto": contrato.get("produto") or "Contrato",
        "modalidade": contrato.get("modalidade") or "CDC",
        "taxa": contrato.get("taxa_juros_mensal"),
        "valor_financiado": dinheiro(contrato["valor_financiado"]),
        "valor_parcela": valor_parcela,
        "total": total,
        "pagas": pagas,
        "proxima": proxima_info,
        "em_atraso": em_atraso,
        "saldo": saldo,
    }


def montar_frase(extratos, quantidade_total):
    if len(extratos) == 1:
        e = extratos[0]
        frase = (f"Seu contrato de {e['produto']}, modalidade {fala_modalidade(e['modalidade'])}, "
                 f"tem valor financiado de {fala_valor(e['valor_financiado'])}. "
                 f"Você já pagou {e['pagas']} de {e['total']} parcelas. ")
        if e["proxima"]:
            if e["em_atraso"]:
                frase += (f"Atenção: há uma parcela vencida desde {fala_data(e['proxima']['vencimento'])}, "
                          f"no valor de {fala_valor(e['proxima']['valor'])}. ")
            else:
                frase += (f"A próxima parcela vence em {fala_data(e['proxima']['vencimento'])}, "
                          f"no valor de {fala_valor(e['proxima']['valor'])}. ")
            frase += f"O saldo devedor aproximado é de {fala_valor(e['saldo'])}. "
        else:
            frase += "Este contrato está quitado. "
        return frase + "Enviamos o extrato completo para o seu e-mail cadastrado."

    frase = (f"Você tem {quantidade_total} contratos ativos. "
             f"Enviamos o extrato de todos para o seu e-mail cadastrado. ")
    atrasados = [e for e in extratos if e["em_atraso"]]
    a_vencer = [e for e in extratos if e["proxima"] and not e["em_atraso"]]
    if atrasados:
        frase += f"Atenção: há parcela vencida no contrato de {atrasados[0]['produto']}. "
    if a_vencer:
        mais_proximo = min(a_vencer, key=lambda e: e["proxima"]["vencimento"])
        frase += (f"O próximo vencimento é em {fala_data(mais_proximo['proxima']['vencimento'])}, "
                  f"do contrato de {mais_proximo['produto']}.")
    return frase.strip()


# ----------------------------------------------------------------------------
# Gerador de PDF minimo (sem bibliotecas): A4, 1 pagina por contrato
# ----------------------------------------------------------------------------
def _esc(texto):
    return texto.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


class Pagina:
    def __init__(self):
        self.ops = []

    def texto(self, x, y, tam, txt, negrito=False):
        fonte = "F2" if negrito else "F1"
        self.ops.append(f"BT /{fonte} {tam} Tf {x:.1f} {y:.1f} Td ({_esc(txt)}) Tj ET")

    def caixa(self, x, y, w, h, preenchimento=None):
        if preenchimento is not None:
            self.ops.append(f"{preenchimento} g {x:.1f} {y:.1f} {w:.1f} {h:.1f} re f 0 g")
        self.ops.append(f"0.6 w {x:.1f} {y:.1f} {w:.1f} {h:.1f} re S")

    def linha(self, x1, y1, x2, y2):
        self.ops.append(f"0.5 w {x1:.1f} {y1:.1f} m {x2:.1f} {y2:.1f} l S")

    def conteudo(self):
        return "\n".join(self.ops).encode("cp1252", errors="replace")


def montar_pdf(paginas):
    """Monta um PDF com varias paginas A4 a partir de uma lista de Pagina."""
    n = len(paginas)
    primeiro_obj_pagina = 5
    ids_pagina = [primeiro_obj_pagina + 2 * i + 1 for i in range(n)]
    kids = " ".join(f"{i} 0 R" for i in ids_pagina)
    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    ]
    for i, pagina in enumerate(paginas):
        conteudo = pagina.conteudo()
        id_conteudo = primeiro_obj_pagina + 2 * i
        objetos.append(b"<< /Length " + str(len(conteudo)).encode() + b" >>\nstream\n"
                       + conteudo + b"\nendstream")
        objetos.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {id_conteudo} 0 R >>".encode())
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objetos, start=1):
        offsets.append(len(pdf))
        pdf += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(pdf)
    pdf += f"xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        pdf += f"{off:010d} 00000 n \n".encode()
    pdf += (f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(pdf)


def pagina_contrato(cliente, e, indice, total_paginas, hoje):
    p = Pagina()
    esq, dir_ = 40, 555
    # Cabecalho
    p.caixa(esq, 770, dir_ - esq, 50, "0.93")
    p.texto(esq + 10, 797, 14, NOME_EMPRESA, negrito=True)
    p.texto(esq + 10, 780, 9, "Extrato de financiamento - DOCUMENTO FICTÍCIO PARA DEMONSTRAÇÃO")
    p.texto(dir_ - 150, 790, 10, f"Emitido em {data_br(hoje)}")
    p.texto(dir_ - 150, 776, 9, f"Contrato {indice} de {total_paginas}")

    # Cliente
    y = 740
    p.texto(esq, y, 8, "CLIENTE")
    p.texto(esq, y - 14, 11, cliente["nome"], negrito=True)
    p.texto(esq, y - 28, 9, f"CPF: {mascarar_cpf(cliente['cpf'])}")
    p.texto(300, y, 8, "CONTRATO")
    p.texto(300, y - 14, 11, e["produto"], negrito=True)
    p.texto(300, y - 28, 9, f"Nº {e['contrato_id']}")
    p.linha(esq, y - 40, dir_, y - 40)

    # Dados do contrato
    y = 665
    p.texto(esq, y + 10, 8, "DADOS DO FINANCIAMENTO")
    taxa = f"{Decimal(str(e['taxa'])):.2f}% ao mês".replace(".", ",") if e["taxa"] is not None else "não informada"
    linhas = [
        ("Modalidade", NOME_MODALIDADE.get(e["modalidade"], e["modalidade"])),
        ("Valor financiado", brl(e["valor_financiado"])),
        ("Taxa de juros", taxa),
        ("Valor da parcela", brl(e["valor_parcela"])),
        ("Parcelas pagas", f"{e['pagas']} de {e['total']}"),
    ]
    for i, (rotulo, valor) in enumerate(linhas):
        yy = y - i * 20
        p.texto(esq + 10, yy - 12, 10, rotulo)
        p.texto(300, yy - 12, 10, valor)
        p.linha(esq, yy - 18, dir_, yy - 18)

    # Situacao
    y = 530
    p.caixa(esq, y - 8, dir_ - esq, 30, "0.97")
    if e["proxima"] is None:
        p.texto(esq + 10, y + 5, 11, "Contrato quitado - nenhuma parcela em aberto", negrito=True)
    elif e["em_atraso"]:
        p.texto(esq + 10, y + 5, 11,
                f"Parcela {e['proxima']['numero']} VENCIDA desde {data_br(e['proxima']['vencimento'])} - "
                f"{brl(e['proxima']['valor'])}", negrito=True)
    else:
        p.texto(esq + 10, y + 5, 11,
                f"Próxima parcela ({e['proxima']['numero']}): vence em {data_br(e['proxima']['vencimento'])} - "
                f"{brl(e['proxima']['valor'])}", negrito=True)

    # Saldo
    y = 470
    p.caixa(esq, y - 8, dir_ - esq, 36, "0.90")
    p.texto(esq + 10, y + 8, 12, "SALDO DEVEDOR APROXIMADO", negrito=True)
    p.texto(dir_ - 130, y + 8, 14, brl(e["saldo"]), negrito=True)
    p.texto(esq, y - 26, 8, "Cálculo: parcelas restantes x valor da parcela, sem considerar juros futuros.")

    # Rodape
    p.texto(esq, 90, 8, "Este documento é totalmente fictício e foi gerado para demonstração. "
                        "Não possui valor contratual ou de cobrança.")
    p.texto(esq, 78, 8, f"{NOME_EMPRESA} (empresa fictícia).")
    return p


def gerar_pdf(cliente, extratos, hoje):
    paginas = [pagina_contrato(cliente, e, i + 1, len(extratos), hoje) for i, e in enumerate(extratos)]
    return montar_pdf(paginas)


# ----------------------------------------------------------------------------
# E-mail (Amazon SES)
# ----------------------------------------------------------------------------
def enviar_email(destino, cliente, extratos, quantidade_total, pdf):
    remetente = os.environ["EMAIL_REMETENTE"]
    assunto = f"Extrato do seu financiamento - {NOME_EMPRESA} (demonstração)"
    primeiro_nome = cliente["nome"].split()[0]

    linhas_txt, linhas_html = [], []
    for e in extratos:
        prox = (f"{data_br(e['proxima']['vencimento'])} ({brl(e['proxima']['valor'])})"
                if e["proxima"] else "quitado")
        linhas_txt.append(f"- {e['produto']} ({e['modalidade']}) - contrato {e['contrato_id']}: "
                          f"{e['pagas']}/{e['total']} parcelas pagas, próxima: {prox}, "
                          f"saldo aproximado {brl(e['saldo'])}")
        linhas_html.append(
            f"<tr><td>{e['produto']}<br><small>{e['modalidade']} - {e['contrato_id']}</small></td>"
            f"<td align='center'>{e['pagas']}/{e['total']}</td><td>{prox}</td>"
            f"<td align='right'>{brl(e['saldo'])}</td></tr>")
    aviso_limite = ""
    if quantidade_total > len(extratos):
        aviso_limite = (f"\nPor limite da demonstração, este e-mail traz {len(extratos)} dos "
                        f"{quantidade_total} contratos.\n")

    texto = (f"Olá, {primeiro_nome}!\n\nSegue em anexo o extrato do seu financiamento.\n\n"
             + "\n".join(linhas_txt) + "\n" + aviso_limite
             + "\nEste e-mail faz parte de uma demonstração e os dados são fictícios.\n")
    html = (f"<html><body style='font-family:Arial,sans-serif'>"
            f"<p>Olá, <b>{primeiro_nome}</b>!</p>"
            f"<p>Segue em anexo o extrato do seu financiamento.</p>"
            f"<table cellpadding='6' style='border-collapse:collapse;min-width:420px' border='1'>"
            f"<tr style='background:#eee'><th>Contrato</th><th>Pagas</th><th>Próxima parcela</th>"
            f"<th>Saldo aprox.</th></tr>{''.join(linhas_html)}</table>"
            f"<p style='color:#777;font-size:12px'>{aviso_limite.strip()}</p>"
            f"<p style='color:#777;font-size:12px'>Este e-mail faz parte de uma demonstração "
            f"e os dados são fictícios.</p></body></html>")

    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = remetente
    msg["To"] = destino
    msg.set_content(texto)
    msg.add_alternative(html, subtype="html")
    msg.add_attachment(pdf, maintype="application", subtype="pdf", filename="extrato-financiamento.pdf")

    ses = boto3.client("ses", region_name="us-east-1")
    ses.send_raw_email(Source=remetente, Destinations=[destino], RawMessage={"Data": msg.as_bytes()})


# ----------------------------------------------------------------------------
# Handler (chamado pelo Amazon Connect)
# ----------------------------------------------------------------------------
def resposta(enviado, **extra):
    base = {"enviado": "true" if enviado else "false", "erro": "false"}
    base.update({k: str(v) for k, v in extra.items()})
    return base


def lambda_handler(event, context):
    parametros = event.get("Details", {}).get("Parameters", {})
    cpf = "".join(c for c in str(parametros.get("cpf", "")) if c.isdigit())
    if len(cpf) != 11:
        return resposta(False, motivo="cpf_invalido")

    try:
        hoje = hoje_br()

        clientes = consultar("clientes", {"cpf": f"eq.{cpf}", "select": "cpf,nome,email", "limit": "1"})
        if not clientes:
            return resposta(False, motivo="cliente_nao_encontrado")
        cliente = clientes[0]

        contratos = consultar("contratos", {
            "cpf": f"eq.{cpf}", "status": "eq.ativo", "order": "contrato_id.asc", "select": "*"})
        if not contratos:
            return resposta(False, motivo="sem_contrato",
                            frase="Não encontramos contratos de financiamento ativos no seu cadastro.")
        quantidade_total = len(contratos)
        contratos = contratos[:MAX_CONTRATOS]

        nao_pagas = consultar("parcelas", {
            "cpf": f"eq.{cpf}", "status": "in.(vencida,aberta)",
            "order": "vencimento.asc", "select": "contrato_id,numero,vencimento,valor"})
        por_contrato = {}
        for parcela in nao_pagas:
            por_contrato.setdefault(parcela["contrato_id"], []).append(parcela)

        extratos = [montar_extrato(c, por_contrato.get(c["contrato_id"], []), hoje) for c in contratos]

        pdf = gerar_pdf(cliente, extratos, hoje)
        enviar_email(cliente["email"], cliente, extratos, quantidade_total, pdf)

        print(f"Extrato enviado com sucesso ({len(extratos)} contrato(s))")
        return resposta(True, frase=montar_frase(extratos, quantidade_total), quantidade=quantidade_total)

    except ClientError as e:
        # Ex.: MessageRejected = e-mail nao verificado no SES (modo sandbox)
        print(f"ERRO no SES: {e.response['Error']['Code']}")
        return {"enviado": "false", "erro": "true", "motivo": e.response["Error"]["Code"]}
    except Exception as e:
        print(f"ERRO: {type(e).__name__}: {e}")
        return {"enviado": "false", "erro": "true"}