# -*- coding: utf-8 -*-
"""
Índices de CNAE usados por /busca/cnae e /busca/cnae_secundario (api_ext).

Fica num arquivo próprio do fork, chamado por dados_cnpj_para_sqlite_progresso.py,
para não alterar dados_cnpj_para_sqlite.py (projeto original; ver README_FORK.md).
Quem gerar a base com o script original roda este módulo depois (veja abaixo).

1) /busca/cnae: índice idx_estabelecimento_cnae_fiscal_cnpj_uf.

2) /busca/cnae_secundario/<codigo>.

estabelecimento.cnae_fiscal_secundaria é um texto "4311801,5510801" e o SQLite
não indexa itens dentro dele. Em vez de indexar todos os secundários da Receita
(centenas de milhões de linhas), cria-se uma tabela derivada só com os CNAEs de
CNAES_SECUNDARIOS_INDEXADOS: um estabelecimento só entra se tiver um desses
códigos entre os secundários, e só o par (código da lista, estabelecimento) é
gravado -- outros secundários do mesmo estabelecimento são ignorados.

Tabelas:
  cnae_secundario_indexados(cnae)  códigos já indexados (a rota responde 404 para
                                   os demais, em vez de uma lista vazia enganosa)
  estabelecimento_cnae_secundario(cnae, cnpj, uf)
                                   PK (cnae, cnpj, uf) WITHOUT ROWID: a própria PK
                                   é o índice, na mesma ordem de
                                   idx_estabelecimento_cnae_fiscal_cnpj_uf

Uso na criação da base: sqls_indexacao() (dados_cnpj_para_sqlite_progresso.py).
Para uma base já pronta (ou gerada pelo script original) e para acrescentar
CNAEs, sem recriá-la:

    python cnae_indices.py ../rede/bases/cnpj.db                   # índice + CNAEs da lista
    python cnae_indices.py ../rede/bases/cnpj.db 5611201 5611203   # + estes CNAEs

Sem códigos, indexa os de CNAES_SECUNDARIOS_INDEXADOS. Rodar de novo para o mesmo
código recarrega só aquele CNAE.
"""
import re
import sqlite3
import sys

# 5510801 hotéis, 5510802 apart-hotéis, 5510803 motéis, 5590601 albergues,
# 5590602 campings, 5590603 pensões, 5590699 outros alojamentos
CNAES_SECUNDARIOS_INDEXADOS = (
    '5510801', '5510802', '5510803',
    '5590601', '5590602', '5590603', '5590699',
)

SQL_INDICE_CNAE_FISCAL = (
    'CREATE INDEX IF NOT EXISTS idx_estabelecimento_cnae_fiscal_cnpj_uf '
    'ON estabelecimento (cnae_fiscal, cnpj, uf)'
)

SQL_CRIA_TABELAS = (
    '''CREATE TABLE IF NOT EXISTS cnae_secundario_indexados (
        cnae TEXT PRIMARY KEY
    )''',
    '''CREATE TABLE IF NOT EXISTS estabelecimento_cnae_secundario (
        cnae TEXT NOT NULL,
        cnpj TEXT NOT NULL,
        uf TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (cnae, cnpj, uf)
    ) WITHOUT ROWID''',
)


def _valida(codigos):
    codigos = tuple(dict.fromkeys(codigos))
    for c in codigos:
        if not re.fullmatch(r'\d{7}', c):
            raise ValueError(f'CNAE deve ter 7 dígitos: {c!r}')
    if not codigos:
        raise ValueError('nenhum CNAE informado')
    return codigos


def sql_preenche(codigos):
    '''INSERT que lê estabelecimento uma vez e grava só os pares com `codigos`.
    json_each separa o texto "a,b,c"; substr(...,-7) devolve o zero à esquerda
    que parte da base omite (151201 -> 0151201), então uma consulta basta.
    OR IGNORE: estabelecimento tem CNPJs repetidos.'''
    lista = ', '.join(f"'{c}'" for c in _valida(codigos))
    return f'''INSERT OR IGNORE INTO estabelecimento_cnae_secundario (cnae, cnpj, uf)
SELECT c, cnpj, uf FROM (
    SELECT substr('0000000' || trim(j.value), -7) AS c, e.cnpj AS cnpj, coalesce(e.uf, '') AS uf
    FROM estabelecimento e,
         json_each('["' || replace(e.cnae_fiscal_secundaria, ',', '","') || '"]') j
    WHERE e.cnae_fiscal_secundaria IS NOT NULL AND e.cnae_fiscal_secundaria <> ''
) WHERE c IN ({lista})'''


def sql_registra(codigos):
    '''Marca os códigos como indexados. Vem depois do preenchimento: se este falhar,
    a rota continua respondendo 404 em vez de uma lista incompleta.'''
    valores = ', '.join(f"('{c}')" for c in _valida(codigos))
    return f'INSERT OR IGNORE INTO cnae_secundario_indexados (cnae) VALUES {valores}'


def sqls_indexacao(codigos=CNAES_SECUNDARIOS_INDEXADOS):
    '''Statements (sem ";" dentro) para a criação da base, na ordem de execução.'''
    return [SQL_INDICE_CNAE_FISCAL, *SQL_CRIA_TABELAS,
            sql_preenche(codigos), sql_registra(codigos)]


def indexa(caminho_db, codigos=CNAES_SECUNDARIOS_INDEXADOS):
    '''Cria as tabelas (se faltarem) e (re)carrega os `codigos`. Idempotente.'''
    codigos = _valida(codigos)
    con = sqlite3.connect(caminho_db)
    try:
        con.execute(SQL_INDICE_CNAE_FISCAL)
        for sql in SQL_CRIA_TABELAS:
            con.execute(sql)
        lista = ', '.join(f"'{c}'" for c in codigos)
        con.execute(f'DELETE FROM cnae_secundario_indexados WHERE cnae IN ({lista})')
        con.execute(f'DELETE FROM estabelecimento_cnae_secundario WHERE cnae IN ({lista})')
        con.execute(sql_preenche(codigos))
        con.execute(sql_registra(codigos))
        con.commit()
        return {
            cnae: n for cnae, n in con.execute(
                'SELECT cnae, count(*) FROM estabelecimento_cnae_secundario '
                f'WHERE cnae IN ({lista}) GROUP BY cnae ORDER BY cnae'
            )
        }
    finally:
        con.close()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    contagem = indexa(sys.argv[1], sys.argv[2:] or CNAES_SECUNDARIOS_INDEXADOS)
    for cnae, n in contagem.items():
        print(f'{cnae}: {n} estabelecimentos')
