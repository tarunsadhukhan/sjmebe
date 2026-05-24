from fastapi.middleware.cors import CORSMiddleware

def add_cors_middleware(app):
    # allow_origin_regex matches any origin so credentials work from any IP/domain
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_origin_regex=r".*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    
