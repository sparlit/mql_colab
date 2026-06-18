import logging
import os
import json

logger = logging.getLogger(__name__)

# ==========================================
# KUBERNETES DEPLOYMENT
# ==========================================

K8S_DEPLOYMENT = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: scalper-pro
  labels:
    app: scalper-pro
spec:
  replicas: 1
  selector:
    matchLabels:
      app: scalper-pro
  template:
    metadata:
      labels:
        app: scalper-pro
    spec:
      containers:
      - name: scalper
        image: scalper-pro:latest
        ports:
        - containerPort: 8050
        resources:
          requests:
            memory: "2Gi"
            cpu: "2"
          limits:
            memory: "4Gi"
            cpu: "4"
        volumeMounts:
        - name: brain-data
          mountPath: /app/brain_data
        env:
        - name: PYTHONUNBUFFERED
          value: "1"
      volumes:
      - name: brain-data
        persistentVolumeClaim:
          claimName: scalper-data-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: scalper-service
spec:
  selector:
    app: scalper-pro
  ports:
  - port: 8050
    targetPort: 8050
  type: ClusterIP
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: scalper-data-pvc
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
"""

K8S_HPA = """
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: scalper-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: scalper-pro
  minReplicas: 1
  maxReplicas: 3
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
"""


class KubernetesDeployer:
    def __init__(self):
        self.configs = {
            "deployment": K8S_DEPLOYMENT,
            "hpa": K8S_HPA,
        }

    def get_config(self, name):
        return self.configs.get(name, "")

    def save_configs(self, directory):
        os.makedirs(directory, exist_ok=True)
        for name, config in self.configs.items():
            with open(os.path.join(directory, f"{name}.yaml"), "w") as f:
                f.write(config)



class RedisClusterManager:
    def __init__(self):
        self.nodes = []
        self.available = False

    def add_node(self, host, port=6379):
        self.nodes.append({"host": host, "port": port})

    def get_client(self):
        try:
            import redis
            if self.nodes:
                host = self.nodes[0]["host"]
                port = self.nodes[0]["port"]
                client = redis.Redis(host=host, port=port, decode_responses=True)
                client.ping()
                self.available = True
                return client
        except (ImportError, ConnectionError) as e:
            logger.debug("Redis client connection failed: %s", e)
        return None


class KafkaProducer:
    def __init__(self):
        self.available = False
        self.topics = []

    def connect(self, bootstrap_servers="localhost:9092"):
        try:
            from kafka import KafkaProducer
            self.producer = KafkaProducer(bootstrap_servers=bootstrap_servers, value_serializer=lambda v: json.dumps(v).encode('utf-8'))
            self.available = True
        except (ImportError, ConnectionError, Exception) as e:
            logger.debug("Kafka connection failed: %s", e)
            self.available = False

    def send(self, topic, message):
        if not self.available:
            return False
        try:
            self.producer.send(topic, value=message)
            self.producer.flush()
            return True
        except (ConnectionError, Exception) as e:
            logger.debug("Kafka send failed for topic %s: %s", topic, e)
            return False


class ClickHouseWriter:
    def __init__(self):
        self.available = False
        self.client = None
        self.url = "http://localhost:8123/"

    def connect(self, host="localhost", port=8123):
        self.url = f"http://{host}:{port}/"
        try:
            import requests
            resp = requests.get(f"http://{host}:{port}/ping", timeout=5)
            self.available = resp.status_code == 200
        except (ConnectionError, ImportError, Exception) as e:
            logger.debug("ClickHouse connection failed: %s", e)
            self.available = False

    def insert_trades(self, trades):
        if not self.available:
            return False
        import requests
        columns = ["time", "symbol", "direction", "volume", "entry", "exit_price", "profit"]
        rows = []
        for trade in trades:
            rows.append([
                str(trade.get('time', '')),
                str(trade.get('symbol', '')),
                int(trade.get('direction', 0)),
                float(trade.get('volume', 0)),
                float(trade.get('entry', 0)),
                float(trade.get('exit', 0)),
                float(trade.get('profit', 0)),
            ])
        if not rows:
            return True
        insert_sql = f"INSERT INTO trades ({', '.join(columns)}) FORMAT JSON"
        json_rows = []
        for row in rows:
            json_rows.append(dict(zip(columns, row)))
        import json as _json
        payload = _json.dumps({"data": json_rows})
        try:
            requests.post(
                self.url,
                params={"query": insert_sql},
                data=payload,
                headers={"Content-Type": "application/json"},
                timeout=5,
            )
        except Exception as e:
            logger.debug("ClickHouse insert failed: %s", e)
        return True


class GrafanaDashboardManager:
    def __init__(self):
        self.dashboards = {
            "trading_overview": self._trading_overview(),
            "system_health": self._system_health(),
            "risk_monitor": self._risk_monitor(),
        }

    def _trading_overview(self):
        return {
            "title": "Trading Overview",
            "panels": [
                {"title": "Equity Curve", "type": "timeseries", "query": "equity"},
                {"title": "Daily PnL", "type": "barchart", "query": "daily_pnl"},
                {"title": "Win Rate", "type": "gauge", "query": "win_rate"},
                {"title": "Open Positions", "type": "table", "query": "positions"},
            ]
        }

    def _system_health(self):
        return {
            "title": "System Health",
            "panels": [
                {"title": "CPU Usage", "type": "timeseries", "query": "cpu"},
                {"title": "Memory Usage", "type": "timeseries", "query": "memory"},
                {"title": "Brain Latency", "type": "timeseries", "query": "brain_latency"},
                {"title": "Error Rate", "type": "timeseries", "query": "errors"},
            ]
        }

    def _risk_monitor(self):
        return {
            "title": "Risk Monitor",
            "panels": [
                {"title": "Drawdown", "type": "timeseries", "query": "drawdown"},
                {"title": "VaR", "type": "gauge", "query": "var"},
                {"title": "Correlation Matrix", "type": "heatmap", "query": "correlations"},
                {"title": "Exposure by Symbol", "type": "piechart", "query": "exposure"},
            ]
        }

    def export_dashboards(self, directory):
        os.makedirs(directory, exist_ok=True)
        for name, dashboard in self.dashboards.items():
            with open(os.path.join(directory, f"{name}.json"), "w") as f:
                json.dump(dashboard, f, indent=2)


class CICDPipeline:
    def __init__(self):
        self.stages = ["lint", "test", "build", "deploy"]

    def generate_github_actions(self):
        return """
name: Scalper Pro CI/CD
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.11'
    - name: Install dependencies
      run: pip install -r requirements.txt
    - name: Lint
      run: python -m py_compile *.py
    - name: Test
      run: python -m pytest tests/ -v
  build:
    needs: test
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    - name: Login to Docker Hub
      uses: docker/login-action@v3
      with:
        username: ${{ secrets.DOCKERHUB_USERNAME }}
        password: ${{ secrets.DOCKERHUB_TOKEN }}
    - name: Build Docker
      run: docker build -t ${{ secrets.DOCKERHUB_USERNAME }}/scalper-pro:${{ github.sha }} .
    - name: Push to registry
      run: docker push ${{ secrets.DOCKERHUB_USERNAME }}/scalper-pro:${{ github.sha }}
  deploy:
    needs: build
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
    - name: Deploy to K8s
      run: kubectl apply -f k8s/
"""

    def save_pipeline(self, directory):
        os.makedirs(os.path.join(directory, ".github", "workflows"), exist_ok=True)
        with open(os.path.join(directory, ".github", "workflows", "ci.yml"), "w") as f:
            f.write(self.generate_github_actions())
