# Android Emulator WebSocket Navigation Testing Guide

## Quick Reference

### System Architecture
- **Backend**: FastAPI (port 8001)
- **WebSocket Endpoint**: `/api/v1/ws/{user_id}?token={jwt_token}`
- **Nginx**: Port 80 (HTTP), 443 (HTTPS)
- **Redis**: Port 6379 (caching, sessions)
- **PostgreSQL**: AWS RDS (transit data)

### Critical Configuration for Android Emulator
- **Emulator → Host IP**: Use `10.0.2.2` instead of `localhost`
- **WebSocket URL**: `ws://10.0.2.2:8001/api/v1/ws/{user_id}?token={jwt_token}`
- **Alternative**: Use ADB port forwarding: `adb reverse tcp:8001 tcp:8001`

## Step-by-Step Testing Process

### 1. Backend Setup
```bash
# Start services
cd C:\Users\yunha\Desktop\kindMap_Algorithm
docker-compose up -d

# Verify health
curl http://localhost:8001/health
# Expected: {"status": "healthy", "redis": "connected", "database": "connected"}
```

### 2. Android Emulator Setup
- **Recommended Device**: Pixel 5+ with Android 11+ (API 30+)
- **Enable GPS**: Settings → Location → Enable
- **Developer Options**: Settings → About → Tap "Build number" 7x
- **Mock Location**: Developer options → Select mock location app

### 3. Network Configuration
**Option A - Use 10.0.2.2 (Recommended)**
```
ws://10.0.2.2:8001/api/v1/ws/{user_id}?token={token}
```

**Option B - ADB Port Forwarding**
```bash
adb reverse tcp:8001 tcp:8001
# Then use: ws://localhost:8001/api/v1/ws/{user_id}?token={token}
```

### 4. JWT Token Authentication
- **Access Token Expiry**: 30 minutes
- **Refresh Token Expiry**: 7 days
- **Guest Mode**: Use `user_id` with `temp_` prefix (e.g., `temp_test_user_123`)

### 5. WebSocket Message Protocol

#### Connection Test
```json
// Send
{"type": "ping"}

// Receive
{"type": "pong"}
```

#### Start Navigation
```json
{
  "type": "start_navigation",
  "origin": "강남역",
  "destination": "서울역",
  "disability_type": "PHY"
}
```

**Disability Types**:
- `PHY`: 지체장애 (Physical/Wheelchair)
- `VIS`: 시각장애 (Visual impairment)
- `AUD`: 청각장애 (Hearing impairment)
- `ELD`: 고령자 (Elderly)

#### Location Update
```json
{
  "type": "location_update",
  "lat": 37.497942,
  "lon": 127.027619,
  "accuracy": 10
}
```

#### Route Operations
```json
// Switch route
{"type": "switch_route", "route_id": 1}

// Recalculate route
{"type": "recalculate_route"}

// End navigation
{"type": "end_navigation"}
```

### 6. Mock GPS Testing
```bash
# Send GPS coordinates via ADB
adb emu geo fix 127.027619 37.497942  # Longitude Latitude (강남역)

# Simulate route movement
adb emu geo gpxload path/to/route.gpx
```

### 7. Server Response Types

| Message Type | Description |
|---|---|
| `route_calculated` | Initial routes computed (top 3) |
| `navigation_update` | Real-time turn-by-turn guidance |
| `route_deviation` | User deviated from route |
| `route_switched` | Route change confirmed |
| `route_recalculated` | New route calculated |
| `arrival` | Destination reached |
| `error` | Error with error_code and message |

### 8. Monitoring and Debugging

#### Backend Logs
```bash
docker-compose logs -f fastapi  # FastAPI logs
docker-compose logs -f redis    # Redis logs
docker-compose logs -f nginx    # Nginx logs
```

#### Android Logs
```bash
adb logcat | grep -i websocket
# Or use Android Studio Logcat window
```

#### Redis Cache Inspection
```bash
docker exec -it kindmap-redis redis-cli
INFO stats          # Cache statistics
KEYS route:*        # Cached routes
KEYS session:*      # Active sessions
```

### 9. Common Test Scenarios

#### Scenario 1: Basic Navigation
1. Connect WebSocket
2. Start navigation (강남역 → 서울역)
3. Send location updates every 5 seconds
4. Verify navigation guidance
5. End navigation

#### Scenario 2: Route Deviation
1. Start navigation
2. Send off-route location
3. Expect `route_deviation` message
4. Verify automatic recalculation

#### Scenario 3: Connection Stability
1. Start navigation
2. Background app (Home button)
3. Verify ping/pong maintained
4. Foreground app
5. Continue navigation

## Troubleshooting

### Cannot Connect to WebSocket
- ✓ Check backend running: `docker-compose ps`
- ✓ Use `10.0.2.2` not `localhost`
- ✓ Verify JWT token not expired (30 min)
- ✓ Check CORS settings in config.py

### Location Updates Not Working
- ✓ Grant GPS permissions in app
- ✓ Location accuracy < 100m
- ✓ Coordinates valid for South Korea
- ✓ Check backend logs for errors

### Route Calculation Fails
- ✓ Verify station names correct
- ✓ Database connected: `curl http://localhost:8001/health`
- ✓ Redis running
- ✓ Valid disability_type: PHY/VIS/AUD/ELD

### Frequent Disconnects
- ✓ Implement ping/pong heartbeat (20s interval)
- ✓ Check Nginx timeout (default: 3600s)
- ✓ Verify network stability
- ✓ Check backend worker capacity (max 1000 connections)

## Best Practices

1. **Heartbeat**: Send ping every 20 seconds
2. **Reconnection**: Exponential backoff strategy
3. **State Management**: Store navigation state locally
4. **Error Handling**: Validate all incoming messages
5. **Permissions**: Request location before navigation
6. **Accuracy**: Use 10-50m for location updates
7. **Token Refresh**: Implement before 30-min expiry
8. **Testing**: Test on emulator first, then real device
9. **Monitoring**: Track battery usage during navigation
10. **Optimization**: Adjust update frequency based on speed

## Key Configuration Files

- **Backend Config**: `transit-routing/app/core/config.py`
- **Environment**: `.env` (JWT secret, DB credentials, ports)
- **Docker**: `docker-compose.yml` (service orchestration)
- **Nginx**: `nginx/conf.d/kindmap_api.conf` (WebSocket proxy)
- **WebSocket Handler**: `transit-routing/app/api/v1/endpoints/websocket.py`

## Testing Tools

- **WebSocket Client Apps**: WebSocket King, Simple WebSocket Client
- **Chrome DevTools**: chrome://inspect → Network → WS
- **Android Studio**: Network Inspector (App Inspection)
- **Postman**: WebSocket request support
- **Load Testing**: websocket-client Python library

## Sample Test Coordinates (Seoul Stations)

| Station | Latitude | Longitude |
|---|---|---|
| 강남역 | 37.497942 | 127.027619 |
| 서울역 | 37.554648 | 126.970880 |
| 잠실역 | 37.513294 | 127.100111 |
| 홍대입구역 | 37.557527 | 126.925382 |

## Performance Expectations

- **Connection Limit**: 1000 concurrent WebSocket connections
- **Session TTL**: 30 minutes (Redis)
- **Route Cache TTL**: 1 hour (Redis)
- **Ping Interval**: 20 seconds
- **Ping Timeout**: 20 seconds
- **Nginx Timeout**: 3600 seconds (1 hour)
- **Workers**: 4 Uvicorn workers

## Related Memories
- `frontend-api-documentation`: Frontend API endpoints and authentication
- `jwt-authentication-api`: JWT token generation and validation
- `transit-routing-analysis`: Routing algorithm and pathfinding service
