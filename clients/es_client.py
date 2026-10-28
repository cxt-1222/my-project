from elasticsearch import AsyncElasticsearch

from core.config import settings
from schemas.search import KnowledgeDoc

es = None

async def init_es():
    global es
    es = AsyncElasticsearch(
        settings.ES_HOST,
        basic_auth=("elastic", settings.ES_BASIC_AUTH)
    )
    # 测试连通性
    if not await es.ping():
        raise RuntimeError("ES 连接失败！")
    print("Elasticsearch connection established.")
    return es

async def get_es():
    global es
    if es is None:
        await init_es()
    return es

async def close_es():
    # 服务关闭，释放连接
    await es.close()


# es 新增
async def add_data(docs:KnowledgeDoc,doc_id,es=None):
    if es is None:
        es = await get_es()
    new_docs = docs.model_dump()
    res = await es.index(
        index=settings.INDEX_NAME,
        id=doc_id,
        document=new_docs
    )
    return res

async def check_data(doc_id,es):
    res = await es.get(index=settings.INDEX_NAME,id=doc_id)
    return res

async def delete_data(doc_id:int,es=None):
    """删除索引中的文档,不存在时忽略"""
    if es is None:
        es = await get_es()
    try:
        await es.delete(index=settings.INDEX_NAME, id=doc_id, refresh=True)
    except Exception:
        # 文档未入索引(草稿/未发布)或已删除,忽略
        pass

def _visible_filter(user_id: int | None):
    """可见性过滤:公开或本人(None=不过滤,兼容非登录场景的调试调用)"""
    if user_id is None:
        return []
    return [{
        'bool': {
            'should': [
                {'term': {'is_public': True}},
                {'term': {'author_id': user_id}},
            ],
            'minimum_should_match': 1,
        }
    }]


# 查询数据
async def search_data(query:str,es:AsyncElasticsearch,user_id:int|None=None):
    res = await es.search(
        index=settings.INDEX_NAME,
        query={
           "bool": {
               "must": [{
                   "multi_match": {
                        "query": query,
                        "analyzer": "ik_smart",
                        "fields": ["title^3","summary^2", "content"],
                        "type": "best_fields"
                   }
               }],
               "filter": _visible_filter(user_id),
           }
        }
    )
    hits = res['hits']['hits']

    new_hits = []
    for h in hits:
        _id = h.get('_id')
        content = h.get('_source').get('content')
        new_hits.append({'_id':_id,'content':content})

    #
    return {
        'msg': '查询成功',
        'data':new_hits
    }

async def search_hightlight_data(query:str,es:AsyncElasticsearch,user_id:int|None=None):
    res = await es.search(
        index=settings.INDEX_NAME,
        query={
            "bool": {
                "must": [{
                    "multi_match": {
                        "query": query,
                        "analyzer": "ik_smart",
                        "fields": ["title^3", "summary^2","content"], # title^3 标题权重3倍高于content
                        "type": "best_fields"
                    }
                }],
                "filter": _visible_filter(user_id),
            }
        },
        # ========= 新增高亮配置 =========
        highlight={
            "pre_tags": ['<span style="background-color: #0010e6;color:#fff;">'],
            "post_tags": ['</span>'],
            "fields": {
                "content": {
                    "fragment_size": 180,        # 摘要片段长度，控制预览文字长短
                    "number_of_fragments": 1,    # 只返回1段摘要（列表预览只需要一段）
                    "no_match_size": 150         # 如果无高亮，截取原文前150字
                }
            }
        }
    )
    hits = res['hits']['hits']

    def _close_span(text: str) -> str:
        # ES 片段在 fragment_size 边界截断时可能不闭合高亮标签,补齐结束标签
        opens = text.count('<span')
        closes = text.count('</span>')
        if opens > closes:
            text += '</span>' * (opens - closes)
        return text

    new_hits = []
    for h in hits:
        _id = h.get('_id')
        # 优先取高亮片段，没有高亮就用原文content
        highlight_content = h.get("highlight", {}).get("content")
        title = h.get('_source').get('title')
        if highlight_content:
            content = _close_span(highlight_content[0]) # 取出第一段高亮摘要
        else:
            content = h.get('_source').get('content')
        new_hits.append({
            'title':title,
            '_id':_id,
            'summary':content
        })
    return new_hits


# 查询全部数据
async def search_all_data(es:AsyncElasticsearch,user_id:int|None=None):
    res = await es.search(
        index=settings.INDEX_NAME,
        query={
            'bool': {
                'must': [{'match_all': {}}],
                'filter': _visible_filter(user_id),
            }
        },
        size=10000  # ES 默认只返回10条，需要显式调大
    )
    hits = res['hits']['hits']
    new_hits = []
    for h in hits:
        new_hits.append({'_id': h.get('_id'), **h.get('_source', {})})
    return new_hits


# 删除全部数据（保留索引结构）
async def delete_all_data(es:AsyncElasticsearch):
    res = await es.delete_by_query(
        index=settings.INDEX_NAME,
        query={'match_all': {}},
        refresh=True
    )
    return {
        'msg': '删除成功',
        'deleted': res.get('deleted', 0)
    }
