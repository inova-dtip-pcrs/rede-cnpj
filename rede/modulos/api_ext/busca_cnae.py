# -*- coding: utf-8 -*-
"""
Buscas por CNAE usadas pelas rotas /busca/cnae e /busca/cnae_secundario de
rede_api_ext.py.

Ficam aqui, e não em rede/rede_sqlite_cnpj.py, para não alterar um arquivo do
projeto original (ver README_FORK.md). Por isso cada função recebe o caminho da
base da Receita (`caminho_db`), em vez de ler o global caminhoDBReceita daquele
módulo; a rota passa rede_relacionamentos.caminhoDBReceita.
"""
import contextlib
import sqlite3

# teto de ids por página, nas duas buscas
LIMITE_MAXIMO = 5000


def _limite(limite_in):
    # limite <= 0 vira 10: no SQLite, LIMIT negativo significa "sem limite"
    return min(limite_in, LIMITE_MAXIMO) if limite_in and limite_in > 0 else 10


def busca_cnae(caminho_db, codigo, limite_in, ultimo_cnpj='', uf=''):
    '''busca os CNPJs cujo CNAE fiscal principal é `codigo` (7 dígitos), uma
    página por vez, em ordem crescente de CNPJ.

    parâmetros (ultimo_cnpj e uf chegam já validados pela rota):
      limite_in   -- tamanho da página (padrão 10, máximo LIMITE_MAXIMO)
      ultimo_cnpj -- último CNPJ da página anterior; '' = 1ª página
      uf          -- sigla do Estado; '' = Brasil inteiro

    retorna (ids, tem_mais):
      ids      -- lista de 'PJ_<cnpj>', sem repetição
      tem_mais -- True se há outra página: pedi-la com ultimo_cnpj = último de ids

    CNAE é um código exato, então consulta direto a tabela estabelecimento
    (sem a busca textual id_search usada por busca_cnpj/busca_cpf).'''
    limite = _limite(limite_in)
    # parte da base grava o CNAE sem o zero à esquerda ("151201" em vez de
    # "0151201"; só códigos iniciados em 0) -- por isso busca as duas formas
    codigo_sem_zero = codigo.lstrip('0') or '0'

    # índice idx_estabelecimento_cnae_fiscal_cnpj_uf (cnae_fiscal, cnpj, uf):
    # as linhas já saem em ordem de CNPJ, e "cnpj > :ultimo_cnpj" pula direto
    # para onde a página anterior parou -- nada é reordenado a cada chamada.
    # Com uf no fim, o mesmo índice filtra por Estado sem ler a tabela.
    # UNION (e não UNION ALL) remove os CNPJs repetidos da tabela antes do
    # LIMIT, para cada página ter `limite` CNPJs distintos.
    query = '''
            SELECT cnpj FROM estabelecimento
            where cnae_fiscal = :codigo and (:uf = '' or uf = :uf) and cnpj > :ultimo_cnpj
            UNION
            SELECT cnpj FROM estabelecimento
            where cnae_fiscal = :codigo_sem_zero and (:uf = '' or uf = :uf) and cnpj > :ultimo_cnpj
            order by cnpj
            limit :limite '''
    with contextlib.closing(sqlite3.connect(caminho_db, uri=True)) as con:
        # limite+1: se a linha extra vier, há outra página (ela não é devolvida)
        cur = con.execute(query, {'codigo': codigo, 'codigo_sem_zero': codigo_sem_zero,
                                  'uf': uf, 'ultimo_cnpj': ultimo_cnpj, 'limite': limite + 1})
        ids = ['PJ_' + k[0] for k in cur]
        cur.close()
    return ids[:limite], len(ids) > limite


def cnae_secundario_indexado(caminho_db, codigo):
    '''True se `codigo` está em cnae_secundario_indexados, ou seja, se
    busca_cnae_secundario cobre esse CNAE. Levanta sqlite3.OperationalError se a
    base não tem a tabela (criada por rede_cria_tabelas/cnae_indices.py).'''
    with contextlib.closing(sqlite3.connect(caminho_db, uri=True)) as con:
        return con.execute('SELECT 1 FROM cnae_secundario_indexados WHERE cnae = ?',
                           (codigo,)).fetchone() is not None


def busca_cnae_secundario(caminho_db, codigo, limite_in, ultimo_cnpj='', uf=''):
    '''como busca_cnae, mas para os CNPJs que têm `codigo` entre os CNAEs
    secundários (o principal pode ser outro). Mesmos parâmetros e retorno
    (ids, tem_mais), mesma paginação por CNPJ.

    Lê a tabela estabelecimento_cnae_secundario (rede_cria_tabelas/cnae_indices.py),
    que só tem os CNAEs de cnae_secundario_indexados: confira com
    cnae_secundario_indexado antes, senão "nenhuma empresa" e "CNAE não indexado"
    ficam indistinguíveis. A PK (cnae, cnpj, uf) serve de índice; o código já está
    com 7 dígitos lá, então não precisa da variante sem zero de busca_cnae.'''
    limite = _limite(limite_in)
    query = '''
            SELECT cnpj FROM estabelecimento_cnae_secundario
            where cnae = :codigo and (:uf = '' or uf = :uf) and cnpj > :ultimo_cnpj
            order by cnpj
            limit :limite '''
    with contextlib.closing(sqlite3.connect(caminho_db, uri=True)) as con:
        cur = con.execute(query, {'codigo': codigo, 'uf': uf, 'ultimo_cnpj': ultimo_cnpj,
                                  'limite': limite + 1})
        ids = ['PJ_' + k[0] for k in cur]
        cur.close()
    return ids[:limite], len(ids) > limite
