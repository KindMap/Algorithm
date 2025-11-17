# custom exception 정의 및 관리


class KindMapException(Exception):  # 예외 구조 정의
    def __init__(self, message: str, code: str = "INTERNAL_ERROR"):
        self.message = message
        self.code = code
        super().__init__(self.message)


class RouteNotFoundException(KindMapException):
    def __init__(self, message: str = "경로를 찾을 수 없습니다"):
        super().__init__(message, code="ROUTE_NOT_FOUND")


class StationNotFoundException(KindMapException):
    def __init__(self, message: str = "역을 찾을 수 없습니다"):
        super().__init__(message, code="STATION_NOT_FOUND")


class SessionNotFoundException(KindMapException):
    def __init__(self, message: str = "세션을 찾을 수 없습니다"):
        super().__init__(message, code="SESSION_NOT_FOUND")


class InvalidLocationException(KindMapException):
    def __init__(self, message: str = "유효하지 않은 위치입니다"):
        super().__init__(message, code="INVALID_LOCATION")
