-- ============================================================================
-- 02_extrato_modalidade.sql
-- Ajustes do banco para a opcao "Extrato de financiamento" (CDC e Finame).
-- Todos os dados sao ficticios.
--
-- ATENCAO: rode UMA VEZ SO, no SQL Editor do Supabase, DEPOIS do 01_banco_demo.sql.
-- Rodar de novo gera erro de duplicidade nos INSERTs e na restricao do bloco 3.
-- Rode um bloco por vez, na ordem.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- Bloco 1: conferir os produtos atuais (so leitura)
-- ----------------------------------------------------------------------------
select produto, count(*) as contratos,
       min(valor_financiado) as menor_valor,
       max(valor_financiado) as maior_valor
from contratos
group by produto
order by produto;


-- ----------------------------------------------------------------------------
-- Bloco 2: colunas novas na tabela contratos
-- ----------------------------------------------------------------------------
alter table contratos add column if not exists modalidade text;
alter table contratos add column if not exists taxa_juros_mensal numeric(5,2);


-- ----------------------------------------------------------------------------
-- Bloco 3: trocar o consorcio de imovel e preencher as colunas novas
-- (o Supabase pode avisar sobre "update sem where": e esperado, pode confirmar)
-- ----------------------------------------------------------------------------
-- 3a. Consorcio de imovel: valores menores viram veiculo, os maiores viram maquinas
update contratos
set produto = case
  when valor_financiado < 30000 then 'Financiamento de Veiculo'
  else 'Financiamento de Maquinas'
end
where produto = 'Consorcio de Imovel';

-- 3b. Modalidade: maquinas = FINAME, o resto = CDC
update contratos
set modalidade = case when produto ilike '%quina%' then 'FINAME' else 'CDC' end;

-- 3c. Taxas ficticias por tipo (% ao mes)
update contratos
set taxa_juros_mensal = case
  when modalidade = 'FINAME' then 1.10
  when produto ilike '%pessoal%' then 3.20
  else 1.85
end;

-- 3d. So aceitar as duas modalidades daqui para frente
alter table contratos
  add constraint contratos_modalidade_check check (modalidade in ('CDC', 'FINAME'));


-- ----------------------------------------------------------------------------
-- Bloco 4: dois clientes de teste novos (CPFs ficticios com digitos validos)
--   Cliente com 1 contrato:  CPF 52998224725
--   Cliente com 3 contratos: CPF 11144477735 (CDC e FINAME)
-- ----------------------------------------------------------------------------
insert into clientes (cpf, nome, telefone, email, data_nascimento, pontos) values
('52998224725', 'Carla Menezes Duarte', '+5541900001001', 'carla.duarte@example.com', '1988-04-17', 1250),
('11144477735', 'Roberto Almeida Pires', '+5541900001002', 'roberto.pires@example.com', '1979-09-03', 4780);

insert into contratos
  (contrato_id, cpf, produto, valor_financiado, parcelas_total, valor_parcela, data_inicio, status, modalidade, taxa_juros_mensal)
select 'CT-900001', '52998224725',
       (select produto from contratos where produto ilike '%culo%' limit 1),
       52000.00, 48, 1496.30, (current_date - interval '8 months')::date + 10, 'ativo', 'CDC', 1.85
union all
select 'CT-900002', '11144477735',
       (select produto from contratos where produto ilike '%culo%' limit 1),
       75000.00, 60, 1890.75, (current_date - interval '14 months')::date + 5, 'ativo', 'CDC', 1.85
union all
select 'CT-900003', '11144477735',
       (select produto from contratos where produto ilike '%pessoal%' limit 1),
       12000.00, 24, 689.40, (current_date - interval '3 months')::date + 20, 'ativo', 'CDC', 3.20
union all
select 'CT-900004', '11144477735',
       (select produto from contratos where produto ilike '%quina%' limit 1),
       380000.00, 72, 7120.00, (current_date - interval '20 months')::date + 15, 'ativo', 'FINAME', 1.10;


-- ----------------------------------------------------------------------------
-- Bloco 5: todas as parcelas dos contratos novos
-- (vencidas no passado = paga; futuras = aberta; assim o saldo devedor sai exato)
-- ----------------------------------------------------------------------------
insert into parcelas (parcela_id, cpf, contrato_id, numero, vencimento, valor, status, linha_digitavel)
select
  c.contrato_id || '#' || lpad(g.n::text, 3, '0'),
  c.cpf,
  c.contrato_id,
  g.n,
  (c.data_inicio + (g.n - 1) * interval '1 month')::date,
  c.valor_parcela,
  case when (c.data_inicio + (g.n - 1) * interval '1 month')::date < current_date
       then 'paga' else 'aberta' end,
  left(translate(md5(random()::text || c.contrato_id) || md5(random()::text || g.n::text) || md5(random()::text),
                 'abcdef', '123456'), 47)
from contratos c
cross join lateral generate_series(1, c.parcelas_total) as g(n)
where c.contrato_id in ('CT-900001', 'CT-900002', 'CT-900003', 'CT-900004');


-- ----------------------------------------------------------------------------
-- Bloco 6: conferir (so leitura)
-- Esperado: cliente 52998224725 com 1 contrato e 8 parcelas pagas;
--           cliente 11144477735 com 3 contratos e 14, 3 e 20 parcelas pagas.
-- ----------------------------------------------------------------------------
select ct.cpf, ct.contrato_id, ct.produto, ct.modalidade, ct.taxa_juros_mensal,
       count(*) filter (where p.status = 'paga') as pagas,
       ct.parcelas_total
from contratos ct
left join parcelas p on p.contrato_id = ct.contrato_id
where ct.cpf in ('52998224725', '11144477735')
group by ct.cpf, ct.contrato_id, ct.produto, ct.modalidade, ct.taxa_juros_mensal, ct.parcelas_total
order by ct.cpf, ct.contrato_id;


-- ----------------------------------------------------------------------------
-- Bloco 7: ajustes feitos nos clientes de teste
-- (nome de um cliente original e e-mail de teste verificado no Amazon SES;
--  para reutilizar em outra conta, troque pelo seu e-mail verificado)
-- O cliente 52998224725 continua como "Carla Menezes Duarte", o nome do bloco 4.
-- ----------------------------------------------------------------------------
update clientes
set nome = 'Nara Geraldo'
where cpf = '64752553430';

update clientes
set email = 'dayaneee.costa1@gmail.com'
where cpf in ('52998224725', '11144477735');
