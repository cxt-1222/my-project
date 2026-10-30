from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # QWEN / 嵌入 / 重排
    QWEN_API_KEY: str
    QWEN_BASE_URL: str
    QWEN_MODEL_NAME: str
    QWEN_VISION_MODEL_NAME: str = ""
    EMBEDDINGS_MODEL_NAME: str
    RERANK_MODEL_NAME: str
    RERANK_URL: str

    # PostgreSQL
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "lyp82nlfxxlE"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5433
    POSTGRES_DB: str = "aiagent"

    # Redis 缓存活跃会话的近期上下文；PostgreSQL 仍是消息主存储
    REDIS_URL: str = "redis://:lyp82nlfxxlE@localhost:6380/0"
    CHAT_CONTEXT_MESSAGE_LIMIT: int = 20
    CHAT_CONTEXT_CACHE_TTL_SECONDS: int = 1800
    CHAT_MEMORY_COLLECTION: str = "chat_memories"
    CHAT_MEMORY_RECALL_LIMIT: int = 5
    CHAT_MEMORY_MAX_PER_TURN: int = 5

    # MongoDB(与 Milvus 共用 DB_NAME)
    MONGO_URI: str
    DB_NAME: str

    # RustFS
    RUSTFS_ENDPOINT: str
    RUSTFS_ACCESS_KEY: str
    RUSTFS_SECRET_KEY: str
    RUSTFS_BUCKET: str
    PRESIGNED_EXPIRE: int = 3600  # 预签名链接有效期，单位秒

    # RabbitMQ
    RABBITMQ_URL: str = "amqp://user:lyp82nlfxxlE@127.0.0.1:5672/aiagent"
    QUEUE_INDEX: str = "INDEX"
    QUEUE_RAG: str = "BY_DOC_IDS"
    QUEUE_KG: str = "BUILD_BY_DOC_IDS"

    # Elasticsearch
    INDEX_NAME: str = 'knowledge-es'
    ES_HOST: str = 'http://localhost:9200'
    ES_BASIC_AUTH: str

    # Milvus
    COLLECTION_NAME: str
    DIMENSIONS: int
    MILVUS_URL: str
    MILVUS_TOKEN: str
    MILVUS_BATCH_SIZE: int = 200      # 攒批写入条数阈值
    MILVUS_BATCH_INTERVAL: float = 5.0  # 攒批最长等待秒数
    MILVUS_SEARCH_TIMEOUT_SECONDS: float = 5.0  # 向量库异常时快速降级到其他召回源

    # Neo4j
    NEO4J_URI: str
    NEO4J_USER: str
    NEO4J_PASSWORD: str
    MAX_CONN_POOL_SIZE: int = 50

    # JWT
    JWT_SECRET_KEY: str = "kh-dev-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440
    JWT_REFRESH_EXPIRE_MINUTES: int = 10080

    # web search
    BOCHAAI_KEY:str = "sk - 170143422d4a482d8cfc8463eca7f372"
    WEB_SEARCH_MIN_SCORE: float = 0.3   # 知识库最高相关分低于此阈值才联网兜底
    WEB_SEARCH_COUNT: int = 5           # 联网返回条数

    # 腾讯云语音(ASR/TTS)，密钥需手动填入 .env；留空时语音接口返回明确错误
    TENCENT_SECRET_ID: str = ""
    TENCENT_SECRET_KEY: str = ""
    TENCENT_APP_ID: str = ""
    TTS_WS_URL: str = "wss://tts.cloud.tencent.com/stream_ws"
    TTS_VOICE_TYPE: int = 502002
    TTS_SAMPLE_RATE: int = 24000
    TTS_CODEC: str = "mp3"
    ASR_ENGINE_MODEL_TYPE: str = "16k_zh_en"
    ASR_VOICE_FORMAT: int = 1  # 1=pcm s16le 16k 单声道，前端按此格式上行
    ASR_NEED_VAD: int = 1

    @property
    def speech_ready(self) -> bool:
        return bool(self.TENCENT_SECRET_ID and self.TENCENT_SECRET_KEY and self.TENCENT_APP_ID)


settings = Settings()
