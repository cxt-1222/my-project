"""
大模型通过读取上传文件内容，抽离出实体和关系，提供给neo4j创建关系
"""
from fastapi import HTTPException
from langchain_openai import ChatOpenAI

from core.config import settings
from models import KHDocument
from schemas.graph import Neo4jSchema

model = ChatOpenAI(
    model=settings.QWEN_MODEL_NAME,
    api_key=settings.QWEN_API_KEY,
    base_url=settings.QWEN_BASE_URL,
    temperature=0
)

def neo4j_prompt(content):
    return f"""
                # 知识图谱抽取任务（Neo4j专用）
                ## 任务描述
                输入一段知识库文章，从中抽取实体、实体间关系，生成可直接导入Neo4j的Cypher语句。
                输出严格为JSON格式，仅有3个顶层字段：实体定义、关系定义、Cypher语句，禁止输出任何前置说明、总结、markdown注释。

                ## 字段详细规范
                1. "entities"：数组
                    单个实体结构：
                    {{
                        "label": "实体标签（英文大驼峰，例如 KnowledgeDoc、TechComponent、Fault）",
                        "name": "实体名称",
                        "properties": {{"属性名":"属性值",...}}
                    }}
                    要求：实体名称尽量唯一，根据文本的语言内容进行标记中文或者其他语言；属性只保留原文出现的信息，不要虚构。

                2. "relationships"：数组
                    单个关系结构：
                    {{
                        "sourceLabel": "起点实体label",
                        "sourceName": "起点实体name",
                        "relName": "关系类型（英文大写下划线，如 DEPEND_ON、BELONG_TO_CATEGORY）",
                        "targetLabel": "终点实体label",
                        "targetName": "终点实体name",
                        "relProps": {{}} //关系属性，无属性填空对象
                    }}
                    要求：关系是有向边，关系动词精简，根据文本的语言内容进行标记中文或者其他语言；不能编造原文不存在关联。

                3. "Cypher语句"：字符串
                    要求：
                    - 使用MERGE而不是CREATE，避免重复创建节点；
                    - MERGE匹配name作为唯一标识；
                    - 依次创建所有节点，再创建全部关系；
                    - Cypher语法可直接复制到Neo4j Browser执行；
                    - 代码放在同一字符串内，换行用\n。

                4. "query_cypher"：字符串
                    要求：
                    - 优先使用MATCH，不要使用CREATE/MERGE等写入语句，只做查询；
                    - 字段返回要贴合业务，不要返回多余属性；支持LIMIT限制返回条数；
                    - 字符串匹配使用$参数形式，避免硬编码字符串，防止Cypher注入；
                    - 如果需要模糊检索，使用 CONTAINS 进行文本匹配;
                    - Cypher语法可直接复制到Neo4j Browser执行；
                    - 代码放在同一字符串内，换行用\n。

                ## 抽取约束
                1. 禁止脑补、推测原文不存在的实体和关系；
                2. 实体标签复用这套体系优先：Enterprise、Department、Employee、KnowledgeDoc、KnowledgeCategory、Business、TechComponent、Fault、Specification；
                3. 技术组件实体：Milvus、ETCD、MinIO、MongoDB、PostgreSQL、Redis、RabbitMQ、Elasticsearch、Neo4j、Docker；
                4. 故障实体记录报错信息、根因、解决方案；
                5. 输出只能是纯JSON，不要```json标记，不要任何额外文字。

                待抽取文本：
                {content}

                """

async def separation_entity_relationship(content) -> Neo4jSchema:
    import json
    import re
    prompt = neo4j_prompt(content)
    resp = await model.ainvoke(prompt)
    text = resp.content.strip()
    # 去掉可能的 markdown 代码块包裹
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        text = match.group(0)
    data = json.loads(text)
    return Neo4jSchema(**data)


async def get_entity_relationship(doc_id: int) -> Neo4jSchema:
    """按 doc_id 从 MongoDB 取正文，抽取实体关系与 Cypher"""
    doc = await KHDocument.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail='文档不存在')
    return await separation_entity_relationship(doc.content)
