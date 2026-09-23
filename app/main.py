from fastapi import FastAPI

app = FastAPI(title="Envira loss-experience service")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
