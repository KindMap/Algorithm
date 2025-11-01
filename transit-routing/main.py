from flask import Flask, request, jsonify
from flasgger import Swagger
from typing import Dict, List, Optional
import logging
from contextlib import contextmanager
from dotenv import load_dotenv

# 환경변수 로드
load_dotenv()

from database import (
    initialize_pool,
    close_pool,
    get_all_stations,
    get_station_by_code,
    get_all_sections,
    get_all_transfer_station_conv_scores,
    get_distance_calculator,
)
from mc_raptor import McRAPTOR
from anp_weights import ANPWeightCalculator
from config import DISABILITY_TYPES

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s : [%(name)s] : %(message)s"
)
logger = logging.getLogger(__name__)
app = Flask(__name__)

# Swagger 설정
swagger_config = {
    "headers": [],
    "specs": [
        {
            "endpoint": "apispec",
            "route": "/apispec.json",
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/api/docs",
}

swagger_template = {
    "swagger": "2.0",
    "info": {
        "title": "Transportation Route API",
        "description": "교통약자 경로 탐색 API",
        "version": "1.0.0",
    },
    "basePath": "/",
    "schemes": ["http", "https"],
}

swagger = Swagger(app, config=swagger_config, template=swagger_template)


def initialize_app():
    """application, database connection pool 초기화"""
    global anp_calculator, mc_raptor

    logger.info("application initializing started")
    initialize_pool()
    anp_calculator = ANPWeightCalculator()

    stations = get_all_stations()
    sections = get_all_sections()
    convenience_scores = get_all_transfer_station_conv_scores()
    distance_calc = get_distance_calculator()

    mc_raptor = McRAPTOR(
        stations=stations,
        sections=sections,
        convenience_scores=convenience_scores,
        distance_calc=distance_calc,
        anp_calculator=anp_calculator,
    )

    logger.info("application initialized")


@app.before_request
def before_request():
    if mc_raptor is None:
        initialize_app()


@app.route("/health", methods=["GET"])
def health_check():
    """
    헬스 체크
    ---
    tags:
      - Health
    responses:
      200:
        description: 서비스 정상 동작
        schema:
          properties:
            status:
              type: string
            message:
              type: string
    """
    return (
        jsonify({"status": "healthy", "message": "Transportation service is running"}),
        200,
    )


@app.route("/api/v1/routes", methods=["POST"])
def find_routes():
    """
    경로 탐색
    ---
    tags:
      - Routes
    parameters:
      - in: body
        name: body
        required: true
        schema:
          type: object
          required:
            - origin
            - destination
            - departure_time
            - disability_type
          properties:
            origin:
              type: string
              example: "0150"
            destination:
              type: string
              example: "0222"
            departure_time:
              type: number
              example: 32400
            disability_type:
              type: string
              enum: [physical, visual, hearing, elderly]
              example: "physical"
            max_rounds:
              type: integer
              default: 4
    responses:
      200:
        description: 경로 탐색 성공
      400:
        description: 잘못된 요청
      500:
        description: 서버 오류
    """
    try:
        data = request.get_json()

        required = ["origin", "destination", "departure_time", "disability_type"]
        for field in required:
            if field not in data:
                return jsonify({"success": False, "error": f"{field} is required"}), 400

        origin = data["origin"]
        destination = data["destination"]
        departure_time = float(data["departure_time"])
        disability_type = data["disability_type"]
        max_rounds = data.get("max_rounds", 4)

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

        ranked_routes = mc_raptor.rank_routes(routes, disability_type)

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
    """
    역 목록 조회
    ---
    tags:
      - Stations
    parameters:
      - in: query
        name: line
        type: string
        required: false
        description: 노선 코드 (선택)
    responses:
      200:
        description: 역 목록
      500:
        description: 서버 오류
    """
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
    """
    특정 역 정보 조회
    ---
    tags:
      - Stations
    parameters:
      - in: path
        name: station_cd
        type: string
        required: true
        description: 역 코드
    responses:
      200:
        description: 역 정보
      404:
        description: 역을 찾을 수 없음
      500:
        description: 서버 오류
    """
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
    """
    지원 장애 유형 목록
    ---
    tags:
      - Configuration
    responses:
      200:
        description: 장애 유형 목록
    """
    return jsonify({"success": True, "disability_types": DISABILITY_TYPES}), 200


@app.teardown_appcontext
def shutdown_session(exception=None):
    pass


def shutdown_hook():
    logger.info("애플리케이션 종료 중...")
    close_pool()
    logger.info("리소스 정리 완료")


if __name__ == "__main__":
    import atexit

    atexit.register(shutdown_hook)
    initialize_app()
    app.run(host="0.0.0.0", port=8001, debug=True)
