"""
标准化错误处理模块
定义统一的错误类型和处理机制
"""

from enum import Enum
from datetime import datetime
from typing import Dict, Any, Optional
import uuid


class ErrorType(Enum):
    """错误类型枚举"""
    # 网络相关错误
    NETWORK_ERROR = "network_error"
    API_LIMIT_ERROR = "api_limit_error"
    TIMEOUT_ERROR = "timeout_error"

    # API 相关错误
    API_AUTH_ERROR = "api_auth_error"
    API_BAD_REQUEST = "api_bad_request"
    API_SERVER_ERROR = "api_server_error"

    # 数据处理错误
    VALIDATION_ERROR = "validation_error"
    PARSE_ERROR = "parse_error"
    DATA_INCONSISTENCY = "data_inconsistency"

    # 业务逻辑错误
    CLUSTERING_ERROR = "clustering_error"
    ANALYSIS_ERROR = "analysis_error"
    RENDER_ERROR = "render_error"

    # 系统错误
    CONFIGURATION_ERROR = "configuration_error"
    STORAGE_ERROR = "storage_error"
    MEMORY_ERROR = "memory_error"


class AppError(Exception):
    """应用异常基类"""

    def __init__(self,
                 error_type: ErrorType,
                 message: str,
                 details: Optional[Dict[str, Any]] = None,
                 error_id: Optional[str] = None):
        super().__init__(message)
        self.error_type = error_type
        self.details = details or {}
        self.error_id = error_id or str(uuid.uuid4())
        self.timestamp = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'error_id': self.error_id,
            'error_type': self.error_type.value,
            'message': str(self),
            'details': self.details,
            'timestamp': self.timestamp.isoformat()
        }


class NetworkError(AppError):
    """网络相关错误"""
    def __init__(self, message: str, url: Optional[str] = None,
                 status_code: Optional[int] = None, **kwargs):
        details = kwargs
        if url:
            details['url'] = url
        if status_code:
            details['status_code'] = status_code

        super().__init__(ErrorType.NETWORK_ERROR, message, details)


class ApiLimitError(AppError):
    """API限制错误"""
    def __init__(self, message: str, retry_after: Optional[int] = None,
                 **kwargs):
        details = kwargs
        if retry_after:
            details['retry_after'] = retry_after

        super().__init__(ErrorType.API_LIMIT_ERROR, message, details)


class ValidationError(AppError):
    """数据验证错误"""
    def __init__(self, message: str, field: Optional[str] = None,
                 value: Optional[Any] = None, **kwargs):
        details = kwargs
        if field:
            details['field'] = field
        if value is not None:
            details['value'] = value

        super().__init__(ErrorType.VALIDATION_ERROR, message, details)


class AnalysisError(AppError):
    """分析错误"""
    def __init__(self, message: str, event_id: Optional[str] = None,
                 **kwargs):
        details = kwargs
        if event_id:
            details['event_id'] = event_id

        super().__init__(ErrorType.ANALYSIS_ERROR, message, details)


def handle_api_error(response):
    """处理API响应错误"""
    if response.status_code == 429:
        retry_after = int(response.headers.get("Retry-After", 60))
        raise ApiLimitError(
            "API rate limit exceeded",
            retry_after=retry_after,
            status_code=response.status_code
        )
    elif response.status_code >= 500:
        raise NetworkError(
            "Server error",
            url=response.url,
            status_code=response.status_code
        )
    elif response.status_code == 401:
        raise AppError(
            ErrorType.API_AUTH_ERROR,
            "Authentication failed",
            status_code=response.status_code
        )
    elif response.status_code == 400:
        raise AppError(
            ErrorType.API_BAD_REQUEST,
            "Bad request",
            status_code=response.status_code
        )


class ErrorHandler:
    """错误处理器"""

    @staticmethod
    def log_error(error: Exception, logger=None):
        """记录错误日志"""
        if isinstance(error, AppError):
            error_info = error.to_dict()

            if logger:
                logger.error(
                    f"AppError: {error.message}",
                    error_type=error.error_type.value,
                    error_id=error.error_id,
                    details=error.details
                )
            else:
                print(f"ERROR: {error_info}")
        else:
            if logger:
                logger.error(f"Unexpected error: {str(error)}",
                           error_type=type(error).__name__)
            else:
                print(f"ERROR: {str(error)}")

    @staticmethod
    def should_retry(error: Exception) -> bool:
        """判断是否应该重试"""
        if isinstance(error, (NetworkError, ApiLimitError, TimeoutError)):
            return True
        if isinstance(error, AppError) and error.error_type in [
            ErrorType.NETWORK_ERROR,
            ErrorType.API_LIMIT_ERROR,
            ErrorType.TIMEOUT_ERROR
        ]:
            return True
        return False

    @staticmethod
    def get_retry_delay(error: Exception) -> float:
        """获取重试延迟"""
        if isinstance(error, ApiLimitError):
            return float(error.details.get('retry_after', 60))
        elif isinstance(error, (NetworkError, TimeoutError)):
            return 1.0  # 默认1秒
        else:
            return 0.5  # 默认0.5秒