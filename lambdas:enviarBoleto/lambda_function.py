"""
Lambda: enviarBoleto   (DEMONSTRACAO - todos os dados sao ficticios)

O que faz, em ordem:
  1. Recebe o CPF do cliente (parametro "cpf" do bloco Lambda do Connect)
  2. Busca no Supabase: cliente, parcela em aberto mais antiga e o contrato
  3. Calcula multa e juros por dia de atraso
  4. Gera um PDF do boleto (sem nenhuma biblioteca externa)
  5. Envia o PDF por e-mail (Amazon SES) para o e-mail cadastrado
  6. Devolve ao Connect uma frase pronta para ser falada

Variaveis de ambiente (configure no console da Lambda):
  SUPABASE_URL           ex: https://abcdefgh.supabase.co
  SUPABASE_SECRET_KEY    chave sb_secret_...
  EMAIL_REMETENTE        e-mail VERIFICADO no Amazon SES
Opcionais (se nao criar, usa o padrao):
  MULTA_PERCENTUAL       padrao 2     (2% de multa)
  JUROS_MES_PERCENTUAL   padrao 1     (1% de juros ao mes)
  DIAS_PRAZO_PAGAMENTO   padrao 3     (boleto atualizado vale por 3 dias)
"""
import json
import os
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from email.message import EmailMessage
from zoneinfo import ZoneInfo

import boto3
from botocore.exceptions import ClientError

CENTAVO = Decimal("0.01")
MESES = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]


# ----------------------------------------------------------------------------
# Configuracao
# ----------------------------------------------------------------------------
def config():
    return {
        "multa": Decimal(os.environ.get("MULTA_PERCENTUAL", "2")) / 100,
        "juros_mes": Decimal(os.environ.get("JUROS_MES_PERCENTUAL", "1")) / 100,
        "prazo": int(os.environ.get("DIAS_PRAZO_PAGAMENTO", "3")),
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
# Calculo de multa e juros
# ----------------------------------------------------------------------------
def calcular_encargos(valor, vencimento, data_pagamento, cfg):
    """Multa fixa (uma vez) + juros simples por dia de atraso (pro rata die)."""
    valor = Decimal(str(valor))
    dias = (data_pagamento - vencimento).days
    if dias <= 0:
        return {"dias": 0, "multa": Decimal("0.00"), "juros": Decimal("0.00"), "total": valor}
    multa = (valor * cfg["multa"]).quantize(CENTAVO, ROUND_HALF_UP)
    juros = (valor * cfg["juros_mes"] / 30 * dias).quantize(CENTAVO, ROUND_HALF_UP)
    return {"dias": dias, "multa": multa, "juros": juros, "total": valor + multa + juros}


# ----------------------------------------------------------------------------
# Formatacao
# ----------------------------------------------------------------------------
def brl(v):
    s = f"{Decimal(v):,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def data_br(d):
    return d.strftime("%d/%m/%Y")


def fala_valor(v):
    v = Decimal(v).quantize(CENTAVO, ROUND_HALF_UP)
    reais, centavos = int(v), int((v * 100) % 100)
    txt = f"{reais} {'real' if reais == 1 else 'reais'}"
    if centavos:
        txt += f" e {centavos} {'centavo' if centavos == 1 else 'centavos'}"
    return txt


def fala_data(d):
    return f"{d.day} de {MESES[d.month - 1]}"


def mascarar_cpf(cpf):
    return f"{cpf[:3]}.***.***-{cpf[-2:]}"


# ----------------------------------------------------------------------------
# Gerador de PDF minimo (sem bibliotecas): 1 pagina A4, fontes Helvetica
# ----------------------------------------------------------------------------
ITF = {"0": "nnwwn", "1": "wnnnw", "2": "nwnnw", "3": "wwnnn", "4": "nnwnw",
       "5": "wnwnn", "6": "nwwnn", "7": "nnnww", "8": "wnnwn", "9": "nwnwn"}


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

    def codigo_barras(self, x, y, altura, digitos, estreito=0.7):
        """Codigo de barras decorativo (Interleaved 2 of 5) - NAO e um boleto real."""
        if len(digitos) % 2:
            digitos += "0"
        elementos = ["n", "n", "n", "n"]  # inicio
        for i in range(0, len(digitos), 2):
            for a, b in zip(ITF[digitos[i]], ITF[digitos[i + 1]]):
                elementos += [a, b]
        elementos += ["w", "n", "n"]  # fim
        pos = x
        for i, e in enumerate(elementos):
            larg = estreito * (3 if e == "w" else 1)
            if i % 2 == 0:  # posicoes pares sao barras pretas
                self.ops.append(f"{pos:.2f} {y:.1f} {larg:.2f} {altura:.1f} re f")
            pos += larg

    def para_bytes(self):
        conteudo = "\n".join(self.ops).encode("cp1252", errors="replace")
        objetos = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> /Contents 4 0 R >>",
            b"<< /Length " + str(len(conteudo)).encode() + b" >>\nstream\n" + conteudo + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        ]
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


def gerar_pdf(cliente, contrato, parcela, enc, vencimento, data_limite, hoje):
    p = Pagina()
    esq, dir_ = 40, 555
    # Cabecalho
    p.caixa(esq, 770, dir_ - esq, 50, "0.93")
    p.texto(esq + 10, 797, 16, "Modo Piloto Consultoria", negrito=True)
    p.texto(esq + 10, 780, 9, "Segunda via de boleto - DOCUMENTO FICTÍCIO PARA DEMONSTRAÇÃO")
    p.texto(dir_ - 150, 790, 10, f"Emitido em {data_br(hoje)}", negrito=False)

    # Dados do pagador e do contrato
    y = 740
    p.texto(esq, y, 8, "PAGADOR")
    p.texto(esq, y - 14, 11, cliente["nome"], negrito=True)
    p.texto(esq, y - 28, 9, f"CPF: {mascarar_cpf(cliente['cpf'])}")
    p.texto(300, y, 8, "CONTRATO")
    p.texto(300, y - 14, 11, contrato.get("produto", "Contrato"), negrito=True)
    p.texto(300, y - 28, 9, f"Nº {parcela['contrato_id']}  |  Parcela {parcela['numero']}")
    p.linha(esq, y - 40, dir_, y - 40)

    # Situacao da parcela
    y = 680
    atrasada = enc["dias"] > 0
    p.caixa(esq, y - 8, dir_ - esq, 30, "0.97")
    if atrasada:
        p.texto(esq + 10, y + 5, 11,
                f"Parcela vencida em {data_br(vencimento)} - {enc['dias']} dia(s) de atraso "
                f"até {data_br(data_limite)}", negrito=True)
    else:
        p.texto(esq + 10, y + 5, 11, f"Parcela com vencimento em {data_br(vencimento)} - sem encargos",
                negrito=True)

    # Tabela de valores
    y = 640
    linhas = [("Valor original da parcela", parcela["valor"]),
              (f"Multa por atraso", enc["multa"]),
              (f"Juros de mora ({enc['dias']} dia(s))", enc["juros"])]
    p.texto(esq, y + 10, 8, "DEMONSTRATIVO DE VALORES")
    for i, (rotulo, valor) in enumerate(linhas):
        yy = y - i * 20
        p.texto(esq + 10, yy - 12, 10, rotulo)
        p.texto(dir_ - 110, yy - 12, 10, brl(valor))
        p.linha(esq, yy - 18, dir_, yy - 18)
    yy = y - len(linhas) * 20
    p.caixa(esq, yy - 36, dir_ - esq, 30, "0.90")
    p.texto(esq + 10, yy - 26, 12, "VALOR TOTAL A PAGAR", negrito=True)
    p.texto(dir_ - 130, yy - 26, 14, brl(enc["total"]), negrito=True)

    # Vencimento para pagamento
    yy -= 70
    p.texto(esq, yy, 8, "PAGAR ATÉ")
    p.texto(esq, yy - 16, 14, data_br(data_limite if atrasada else vencimento), negrito=True)
    p.texto(300, yy, 8, "BENEFICIÁRIO")
    p.texto(300, yy - 16, 11, "Modo Piloto Consultoria", negrito=True)

    # Linha digitavel e codigo de barras (decorativos)
    yy -= 60
    p.caixa(esq, yy - 85, dir_ - esq, 100)
    p.texto(esq + 10, yy + 2, 8, "LINHA DIGITÁVEL (FICTÍCIA)")
    p.texto(esq + 10, yy - 16, 12, parcela["linha_digitavel"], negrito=True)
    digitos = "".join(c for c in parcela["linha_digitavel"] if c.isdigit())[:44]
    p.codigo_barras(esq + 10, yy - 78, 45, digitos)

    # Rodape
    p.texto(esq, 90, 8, "Este documento é totalmente fictício e foi gerado para demonstração. "
                        "Não possui valor de cobrança e não pode ser pago.")
    p.texto(esq, 78, 8, "Valores calculados com multa e juros configuráveis (parâmetros de demonstração).")
    return p.para_bytes()


# ----------------------------------------------------------------------------
# E-mail (Amazon SES)
# ----------------------------------------------------------------------------
def enviar_email(destino, cliente, parcela, enc, vencimento, data_limite, pdf):
    remetente = os.environ["EMAIL_REMETENTE"]
    atrasada = enc["dias"] > 0
    assunto = "Segunda via do seu boleto - Modo Piloto Consultoria (demonstração)"
    primeiro_nome = cliente["nome"].split()[0]
    pagar_ate = data_limite if atrasada else vencimento

    detalhes_txt = (f"Valor original: {brl(parcela['valor'])}\n"
                    f"Multa: {brl(enc['multa'])}\nJuros ({enc['dias']} dia(s)): {brl(enc['juros'])}\n"
                    if atrasada else f"Valor: {brl(parcela['valor'])}\n")
    texto = (f"Olá, {primeiro_nome}!\n\nSegue em anexo a segunda via do seu boleto.\n\n"
             f"{detalhes_txt}Valor total: {brl(enc['total'])}\nPagar até: {data_br(pagar_ate)}\n\n"
             "Este e-mail faz parte de uma demonstração e os dados são fictícios.\n")

    if atrasada:
        linhas_html = (f"<tr><td>Valor original</td><td align='right'>{brl(parcela['valor'])}</td></tr>"
                       f"<tr><td>Multa</td><td align='right'>{brl(enc['multa'])}</td></tr>"
                       f"<tr><td>Juros de mora ({enc['dias']} dia(s))</td>"
                       f"<td align='right'>{brl(enc['juros'])}</td></tr>")
    else:
        linhas_html = f"<tr><td>Valor</td><td align='right'>{brl(parcela['valor'])}</td></tr>"
    html = (f"<html><body style='font-family:Arial,sans-serif'>"
            f"<p>Olá, <b>{primeiro_nome}</b>!</p>"
            f"<p>Segue em anexo a segunda via do seu boleto.</p>"
            f"<table cellpadding='6' style='border-collapse:collapse;min-width:320px'>{linhas_html}"
            f"<tr style='border-top:2px solid #333'><td><b>Total</b></td>"
            f"<td align='right'><b>{brl(enc['total'])}</b></td></tr></table>"
            f"<p>Pagar até: <b>{data_br(pagar_ate)}</b></p>"
            f"<p style='color:#777;font-size:12px'>Este e-mail faz parte de uma demonstração "
            f"e os dados são fictícios.</p></body></html>")

    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = remetente
    msg["To"] = destino
    msg.set_content(texto)
    msg.add_alternative(html, subtype="html")
    msg.add_attachment(pdf, maintype="application", subtype="pdf", filename="boleto-atualizado.pdf")

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
        cfg = config()
        hoje = hoje_br()

        clientes = consultar("clientes", {"cpf": f"eq.{cpf}", "select": "cpf,nome,email", "limit": "1"})
        if not clientes:
            return resposta(False, motivo="cliente_nao_encontrado")
        cliente = clientes[0]

        # parcela nao paga mais antiga: se houver vencida, vem primeiro; senao, a proxima a vencer
        parcelas = consultar("parcelas", {
            "cpf": f"eq.{cpf}", "status": "in.(vencida,aberta)",
            "order": "vencimento.asc", "limit": "1", "select": "*"})
        if not parcelas:
            return resposta(False, motivo="sem_boleto",
                            frase="Você não tem boletos em aberto no momento.")
        parcela = parcelas[0]
        vencimento = date.fromisoformat(parcela["vencimento"])

        contratos = consultar("contratos", {
            "contrato_id": f"eq.{parcela['contrato_id']}", "select": "produto", "limit": "1"})
        contrato = contratos[0] if contratos else {}

        atrasada = vencimento < hoje
        data_limite = hoje + timedelta(days=cfg["prazo"]) if atrasada else vencimento
        enc = calcular_encargos(parcela["valor"], vencimento, data_limite, cfg)

        pdf = gerar_pdf(cliente, contrato, parcela, enc, vencimento, data_limite, hoje)
        enviar_email(cliente["email"], cliente, parcela, enc, vencimento, data_limite, pdf)

        if atrasada:
            dias_hoje = (hoje - vencimento).days
            frase = (f"Encontramos uma parcela vencida há {dias_hoje} {'dia' if dias_hoje == 1 else 'dias'}. "
                     f"O valor atualizado, com multa e juros, para pagamento até {fala_data(data_limite)}, "
                     f"é de {fala_valor(enc['total'])}. "
                     f"Enviamos o boleto para o seu e-mail cadastrado.")
        else:
            frase = (f"Sua próxima parcela vence em {fala_data(vencimento)}, "
                     f"no valor de {fala_valor(enc['total'])}. "
                     f"Enviamos o boleto para o seu e-mail cadastrado.")
        print("Boleto enviado com sucesso")
        dias_atraso = (hoje - vencimento).days if atrasada else 0
        return resposta(True, frase=frase, dias_atraso=dias_atraso,
                        valor_atualizado=str(enc["total"]).replace(".", ","))

    except ClientError as e:
        # Ex.: MessageRejected = e-mail nao verificado no SES (modo sandbox)
        print(f"ERRO no SES: {e.response['Error']['Code']}")
        return {"enviado": "false", "erro": "true", "motivo": e.response["Error"]["Code"]}
    except Exception as e:
        print(f"ERRO: {type(e).__name__}: {e}")
        return {"enviado": "false", "erro": "true"}