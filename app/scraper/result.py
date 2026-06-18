class ScrapeResult(list):
    def __init__(self, items=(), metadata: dict | None = None):
        super().__init__(items)
        self.metadata = metadata or {}
