# PAD Backend

## Running the project locally

### Prerequisites

1. You must have docker and docker-compose functionally in your environment
2. You must have python or python package manager such ac conda, miniconda, etc installed

### Steps

1. Download the dependency 

```bash
conda create -n backend python=3.13
conda activate backend
pip install uv
uv sync
```

2. Run Docker Compose

```bash
docker-compose up mongo postgres qdrant minio
```

3. Run the backend

```bash
uv run python -m app
```

4. Swagger UI

The API documentation can be accessed through the Swagger UI at `http://localhost:8000/api/docs`

5. Shutdown the backend

```bash
docker-compose down
# or to remove volumes and networks
docker-compose down -v
```

6. You will docker image left over of postgresql, qdrant, minio, mongodb
