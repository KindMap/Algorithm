from flask import Flask, request, jsonify
from typing import Dict, List, Optional
import logging
from contextlib import contextmanager

from database import (
    initialize_pool,
    close_pool,
    get_all_stations,
    get_all_sections,
    get_all_transfer_station_conv_scores,
    get_distance_calculator,
)
from mc_raptor import McRAPTOR
from anp_weights import ANPWeightCalculator
from config import DISABILITY_TYPES

# logging level 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s : [%(name)s] : %(message)s'
)
logger = logging.getLogger(__name__)
app = Flask(__name__)

def initialize_app():
    """application, database connection pool 초기화"""
    global anp_calculator, mc_raptor
    
    logger.info("application initializing started")
    
    # database connection pool initialized
    initialize_pool()
    
    anp_calculator = ANPWeightCalculator()
    
    # data loading
    stations = get_all_stations()
    sections = get_all_sections()
    convenience_scores = get_all_transfer_station_conv_scores()
    distance_calc = get_distance_calculator()
    
    # create McRAPTOR instance
    mc_raptor = McRAPTOR(
        stations=stations,
        sections=sections,
        convenience_scores=convenience_scores,
        distance_calc=distance_calc,
        anp_calculator=anp_calculator
    )
    
    logger.info("application initialized")

@app.before_request
def before_request():
    """requst전처리"""
    # request를 받기 전에 반드시 app이 초기화되도록 함
    if mc_raptor is None:
        initialize_app()


@app.route('/health', methods=['GET'])
def health_check():
    """헬스 체크"""
    return (
        jsonify({"status": "healthy", "message": "Transportation service is running"}),
        200,
    )


@app.route("/api/v1/routes", methods=["POST"])
def find_routes():
    """경로 탐색 API"""
    try:
        data = request.get_json()

        # 필수 파라미터 검증
        required = ["origin", "destination", "departure_time", "disability_type"]
        for field in required:
            if field not in data:
                return jsonify({"success": False, "error": f"{field} is required"}), 400

        origin = data["origin"]
        destination = data["destination"]
        departure_time = float(data["departure_time"])
        disability_type = data["disability_type"]
        max_rounds = data.get("max_rounds", 4)

        # 장애 유형 검증
        if disability_type not in DISABILITY_TYPES:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"Invalid disability_type. Must be one of {list(DISABILITY_TYPES.keys())}",
                    }
                ),
                400,
            )

        # 경로 탐색
        routes = mc_raptor.find_routes(
            origin=origin,
            destination=destination,
            departure_time=departure_time,
            disability_type=disability_type,
            max_rounds=max_rounds,
        )

        if not routes:
            return (
                jsonify({"success": True, "message": "No routes found", "routes": []}),
                200,
            )

        # 경로 순위 결정
        ranked_routes = mc_raptor.rank_routes(routes, disability_type)

        # 응답 포맷팅
        response_routes = []
        for rank, (route, score) in enumerate(ranked_routes, 1):
            response_routes.append(
                {
                    "rank": rank,
                    "score": round(score, 4),
                    "arrival_time": round(route.arrival_time, 2),
                    "transfers": route.transfers,
                    "walking_distance": round(route.walking_distance, 2),
                    "convenience_score": round(route.convenience_score, 2),
                    "route": route.route,
                    "lines": route.lines,
                }
            )

        return (
            jsonify(
                {
                    "success": True,
                    "disability_type": disability_type,
                    "origin": origin,
                    "destination": destination,
                    "routes": response_routes,
                }
            ),
            200,
        )

    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"Error in find_routes: {e}", exc_info=True)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@app.route("/api/v1/stations", methods=["GET"])
def get_stations():
    """역 목록 조회 API"""
    try:
        line = request.args.get("line")
        stations = get_all_stations(line=line)

        return (
            jsonify({"success": True, "count": len(stations), "stations": stations}),
            200,
        )

    except Exception as e:
        logger.error(f"Error in get_stations: {e}", exc_info=True)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@app.route("/api/v1/stations/<station_cd>", methods=["GET"])
def get_station(station_cd):
    """특정 역 정보 조회 API"""
    try:
        station = get_station_by_code(station_cd)

        if not station:
            return jsonify({"success": False, "error": "Station not found"}), 404

        return jsonify({"success": True, "station": station}), 200

    except Exception as e:
        logger.error(f"Error in get_station: {e}", exc_info=True)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@app.route("/api/v1/disability-types", methods=["GET"])
def get_disability_types():
    """지원 장애 유형 목록"""
    return jsonify({"success": True, "disability_types": DISABILITY_TYPES}), 200


@app.teardown_appcontext
def shutdown_session(exception=None):
    """애플리케이션 종료 시 리소스 정리"""
    pass


def shutdown_hook():
    """종료 훅"""
    logger.info("애플리케이션 종료 중...")
    close_pool()
    logger.info("리소스 정리 완료")


if __name__ == "__main__":
    import atexit

    atexit.register(shutdown_hook)

    # 애플리케이션 초기화
    initialize_app()

    # Flask 서버 실행
    app.run(host="0.0.0.0", port=8001, debug=True)
