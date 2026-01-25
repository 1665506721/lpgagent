"""应用配置管理。"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置，统一从环境变量加载。"""

    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False)

    # 应用名称，用于日志标识与服务识别
    APP_NAME: str = "admission_api"
    # 运行环境，例如：development / staging / production
    APP_ENV: str = "development"
    # 日志级别，例如：DEBUG / INFO / WARNING / ERROR
    LOG_LEVEL: str = "INFO"
    # 管理接口鉴权 Token，用于校验 X-Admin-Token
    ADMIN_TOKEN: str = ""
    # Kafka 集群地址，例如：localhost:9092
    KAFKA_BOOTSTRAP_SERVERS: str = ""
    # 下单消息主题
    KAFKA_TOPIC_ORDER_CREATE: str = "order_create"


settings = Settings()
