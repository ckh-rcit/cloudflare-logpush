"""
Cloudflare Logpush HTTP Receiver
Receives gzipped JSON logs from Cloudflare and forwards to Loki
"""

import os
import gzip
import json
import time
import logging
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# Configuration
LOKI_URL = os.getenv('LOKI_URL', 'http://loki:3100')
AUTH_TOKEN = os.getenv('AUTH_TOKEN', 'changeme')
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

# Setup logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def push_to_loki(logs: list, labels: dict = None):
    """Push logs to Loki"""
    if not logs:
        return True
    
    if labels is None:
        labels = {"job": "cloudflare", "source": "logpush"}
    
    # Build Loki push format
    streams = []
    values = []
    
    for log in logs:
        # Use EdgeStartTimestamp if available, otherwise current time
        timestamp = log.get('EdgeStartTimestamp')
        if timestamp:
            # Convert RFC3339 to nanoseconds
            try:
                from datetime import datetime
                if isinstance(timestamp, str):
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    ts_ns = str(int(dt.timestamp() * 1e9))
                else:
                    ts_ns = str(int(time.time() * 1e9))
            except:
                ts_ns = str(int(time.time() * 1e9))
        else:
            ts_ns = str(int(time.time() * 1e9))
        
        values.append([ts_ns, json.dumps(log)])
    
    streams.append({
        "stream": labels,
        "values": values
    })
    
    payload = {"streams": streams}
    
    try:
        response = requests.post(
            f"{LOKI_URL}/loki/api/v1/push",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to push to Loki: {e}")
        return False


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "healthy"}), 200


@app.route('/', methods=['POST', 'GET'])
@app.route('/logs', methods=['POST', 'GET'])
@app.route('/api/logs', methods=['POST', 'GET'])
def receive_logs():
    """
    Receive logs from Cloudflare Logpush
    
    Cloudflare sends:
    - Gzipped NDJSON (newline-delimited JSON)
    - POST request with gzip content
    - For validation: sends test.txt.gz with {"content":"tests"}
    """
    
    # Handle validation request from Cloudflare
    if request.method == 'GET':
        return jsonify({"status": "ok", "message": "Cloudflare Logpush receiver ready"}), 200
    
    # Optional: Validate auth token
    auth_header = request.headers.get('Authorization', '')
    if AUTH_TOKEN != 'changeme':
        expected_auth = f"Bearer {AUTH_TOKEN}"
        if auth_header != expected_auth and AUTH_TOKEN not in request.args.get('token', ''):
            logger.warning(f"Unauthorized request from {request.remote_addr}")
            return jsonify({"error": "Unauthorized"}), 401
    
    try:
        # Get raw data
        data = request.get_data()
        
        if not data:
            logger.warning("Received empty request")
            return jsonify({"error": "No data received"}), 400
        
        # Try to decompress gzipped data
        try:
            decompressed = gzip.decompress(data)
            content = decompressed.decode('utf-8')
        except gzip.BadGzipFile:
            # Not gzipped, use raw data
            content = data.decode('utf-8')
        except Exception as e:
            logger.warning(f"Decompression failed, trying raw: {e}")
            content = data.decode('utf-8')
        
        # Handle Cloudflare validation test
        if '{"content":"tests"}' in content:
            logger.info("Received Cloudflare validation request")
            return jsonify({"text": "Success", "code": 0}), 200
        
        # Parse NDJSON (newline-delimited JSON)
        logs = []
        for line in content.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            try:
                log_entry = json.loads(line)
                logs.append(log_entry)
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse log line: {e}")
                continue
        
        if not logs:
            logger.info("No valid logs to process")
            return jsonify({"status": "ok", "processed": 0}), 200
        
        # Extract labels from first log entry for better querying
        sample_log = logs[0]
        labels = {
            "job": "cloudflare",
            "source": "logpush"
        }
        
        # Add zone/domain if available
        if 'ClientRequestHost' in sample_log:
            labels["host"] = sample_log['ClientRequestHost']
        
        # Push to Loki
        success = push_to_loki(logs, labels)
        
        if success:
            logger.info(f"Successfully processed {len(logs)} log entries")
            return jsonify({"status": "ok", "processed": len(logs)}), 200
        else:
            return jsonify({"error": "Failed to push to Loki"}), 500
            
    except Exception as e:
        logger.error(f"Error processing logs: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/test', methods=['POST'])
def test_endpoint():
    """Test endpoint to verify the receiver is working"""
    test_log = {
        "ClientIP": "1.2.3.4",
        "ClientRequestHost": "test.example.com",
        "ClientRequestMethod": "GET",
        "ClientRequestURI": "/test",
        "EdgeResponseStatus": 200,
        "EdgeStartTimestamp": "2024-01-01T00:00:00Z",
        "RayID": "test-ray-id"
    }
    
    success = push_to_loki([test_log], {"job": "cloudflare", "source": "test"})
    
    if success:
        return jsonify({"status": "ok", "message": "Test log pushed to Loki"}), 200
    else:
        return jsonify({"error": "Failed to push test log"}), 500


if __name__ == '__main__':
    logger.info(f"Starting Cloudflare Logpush receiver on port 8088")
    logger.info(f"Loki URL: {LOKI_URL}")
    
    # Use gunicorn in production
    from gunicorn.app.base import BaseApplication
    
    class StandaloneApplication(BaseApplication):
        def __init__(self, app, options=None):
            self.options = options or {}
            self.application = app
            super().__init__()

        def load_config(self):
            for key, value in self.options.items():
                if key in self.cfg.settings and value is not None:
                    self.cfg.set(key.lower(), value)

        def load(self):
            return self.application

    options = {
        'bind': '0.0.0.0:8088',
        'workers': 2,
        'timeout': 120,
        'accesslog': '-',
        'errorlog': '-',
        'loglevel': LOG_LEVEL.lower()
    }
    
    StandaloneApplication(app, options).run()
