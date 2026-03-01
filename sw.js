@app.get("/sw.js")
def serve_sw():
    base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, "sw.js")
    return FileResponse(path, media_type="application/javascript")
