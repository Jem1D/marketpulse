from fastapi import FastAPI


app = FastAPI(
    title="MarketPulse API",
    description="Real-Time Reddit x Stock Correlation Engine",
    version="0.1.0",
)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", tags=["system"])
def root() -> dict[str, str]:
    return {"message": "MarketPulse API is running"}
