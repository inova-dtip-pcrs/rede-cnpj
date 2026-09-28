# -*- coding: utf-8 -*-
"""
Blueprint com rotas /api adicionais deste fork, reaproveitando as funções de
acesso a dados já existentes em rede_sqlite_cnpj.py.

Registrado apenas em deploy/wsgi.py (não em rede/rede.py), para não exigir
nenhuma alteração nos arquivos originais do projeto.
"""
from flask import Blueprint, request, abort, Response
from orjson import dumps as jsonify

# siglas aceitas no parâmetro uf de /busca/cnae: os valores que aparecem em
# estabelecimento.uf na base da Receita (27 UFs + EX = endereço no exterior)
UFS_VALIDAS = {
    'AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MG', 'MS',
    'MT', 'PA', 'PB', 'PE', 'PI', 'PR', 'RJ', 'RN', 'RO', 'RR', 'RS', 'SC',
    'SE', 'SP', 'TO', 'EX',
}


def criar_blueprint(rede_mod):
    """rede_mod = o módulo rede.py já carregado e inicializado (via wsgi.py),
    com sys.argv/sys.path/cwd isolados. Não importamos rede_sqlite_cnpj nem
    rede_config diretamente aqui para não reexecutar o argparse de
    rede_config.py contra o sys.argv real do gunicorn."""

    rede_relacionamentos = rede_mod.rede_relacionamentos
    limiter = rede_mod.limiter
    gLock = rede_mod.gLock
    gUwsgiLock = rede_mod.gUwsgiLock
    uwsgi_mod = getattr(rede_mod, 'uwsgi', None)  # só existe sob uWSGI de verdade
    limiter_dados = rede_mod.limiter_dados
    api_key_validas = rede_mod.api_key_validas
    cfg = rede_mod.config.config  # rede_mod.config é o módulo rede_config; .config é o ConfigParser

    bp = Blueprint('api_ext', __name__)

    def _checa_chave():
        chave = request.args.get('api_key') or request.headers.get('X-API-Key', '')
        # mesma checagem dupla de rede.py:345 -- com api_keys='' no rede.ini,
        # api_key_validas == [''], então "chave not in api_key_validas" sozinho
        # deixaria passar requisições sem chave.
        if (chave not in api_key_validas) or not chave:
            abort(401, description='Chave inválida')

    def _com_lock(fn, *args, **kwargs):
        try:
            if gUwsgiLock and uwsgi_mod:
                uwsgi_mod.lock()
            with gLock:
                return fn(*args, **kwargs)
        finally:
            if gUwsgiLock and uwsgi_mod:
                uwsgi_mod.unlock()

    def _resposta_json(dados):
        return Response(jsonify(dados), mimetype='application/json')

    if cfg['API'].getboolean('api_ext_busca', False):

        @bp.route('/busca/nome', methods=['GET'])
        @limiter.limit(limiter_dados)
        def busca_nome():
            if cfg['API'].getboolean('api_ext_requer_chave', False):
                _checa_chave()
            nome = request.args.get('q', '').strip()
            limite = request.args.get('limite', 10, type=int)
            if not nome:
                return abort(400, description='parâmetro q obrigatório')
            ids = _com_lock(rede_relacionamentos.buscaPorNome, nome, limite)
            return _resposta_json({'ids': sorted(ids)})

        @bp.route('/busca/cnpj_raiz/<cnpj_basico>', methods=['GET'])
        @limiter.limit(limiter_dados)
        def busca_cnpj_raiz(cnpj_basico):
            if cfg['API'].getboolean('api_ext_requer_chave', False):
                _checa_chave()
            if not (cnpj_basico.isdigit() and len(cnpj_basico) == 8):
                return abort(400, description='cnpj_basico deve ter 8 dígitos')
            limite = request.args.get('limite', 10, type=int)
            ids = _com_lock(rede_relacionamentos.busca_cnpj, cnpj_basico, limite)
            return _resposta_json({'ids': sorted(ids)})

        @bp.route('/busca/cnae/<codigo>', methods=['GET'])
        @limiter.limit(limiter_dados)
        def busca_cnae_codigo(codigo):
            if cfg['API'].getboolean('api_ext_requer_chave', False):
                _checa_chave()
            if not (codigo.isdigit() and len(codigo) == 7):
                return abort(400, description='codigo deve ter 7 dígitos')
            # proxima_pagina: valor recebido no campo de mesmo nome da resposta
            # anterior (é o último CNPJ daquela página); ausente = 1ª página
            proxima_pagina = request.args.get('proxima_pagina', '')
            if proxima_pagina and not (proxima_pagina.isdigit() and len(proxima_pagina) == 14):
                return abort(400, description='proxima_pagina inválida: use o valor recebido na resposta anterior')
            uf = request.args.get('uf', '').strip().upper()
            if uf and uf not in UFS_VALIDAS:
                return abort(400, description='uf deve ser a sigla de um Estado (ex.: RS) ou EX')
            limite = request.args.get('limite', 10, type=int)
            ids, tem_mais = _com_lock(rede_relacionamentos.busca_cnae, codigo, limite, proxima_pagina, uf)
            # sem sorted(): busca_cnae já devolve em ordem de CNPJ, e essa
            # ordem é o que faz a paginação funcionar.
            # proxima_pagina = valor a reenviar, no parâmetro de mesmo nome,
            # para pegar a página seguinte; None quando não há mais nada (já
            # na 1ª resposta, se tudo coube numa página).
            proxima = ids[-1][3:] if tem_mais else None
            return _resposta_json({'ids': ids, 'proxima_pagina': proxima})

        @bp.route('/busca/cpf/<cpf_parcial>', methods=['GET'])
        @limiter.limit(limiter_dados)
        def busca_cpf_parcial(cpf_parcial):
            if cfg['API'].getboolean('api_ext_requer_chave', False):
                _checa_chave()
            if len(cpf_parcial) < 9:  # busca_cpf usa cpfin[3:9]
                return abort(400, description='cpf_parcial curto demais')
            limite = request.args.get('limite', 10, type=int)
            ids = _com_lock(rede_relacionamentos.busca_cpf, cpf_parcial, limite)
            return _resposta_json({'ids': sorted(ids)})

    if cfg['API'].getboolean('api_ext_dados', False):

        @bp.route('/dados', methods=['GET'])
        @limiter.limit(limiter_dados)
        def dados_por_ids():
            if cfg['API'].getboolean('api_ext_requer_chave', False):
                _checa_chave()
            ids_param = request.args.get('ids', '')
            bsocios = request.args.get('socios', '0') == '1'
            lista_ids = [i.strip() for i in ids_param.split(',') if i.strip()]
            if not lista_ids:
                return abort(400, description='parâmetro ids obrigatório (separado por vírgula)')
            dados = _com_lock(rede_relacionamentos.jsonDados, lista_ids, bsocios)
            return _resposta_json(dados)

    return bp
