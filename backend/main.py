from fastapi import FastAPI

app = FastAPI(title="RepoPilot AI")

@app.get("/")
def home():
    return {"message": "RepoPilot AI Backend Running"}

@app.get("/health")
def health():
    return {"status": "healthy"}